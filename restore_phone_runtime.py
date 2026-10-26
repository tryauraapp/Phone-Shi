#!/usr/bin/env python3
"""Restore and verify host/runtime state for one certified lab phone boot."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent


def avd_directory(avd):
    home = Path(os.environ.get('ANDROID_AVD_HOME') or Path.home() / '.android/avd')
    directory = home / (avd + '.avd')
    registration = home / (avd + '.ini')
    if registration.is_file():
        for line in registration.read_text().splitlines():
            if line.startswith('path='):
                directory = Path(line[5:])
                break
    return directory


def load_runtime(avd, backups=None):
    backups = Path(backups) if backups else Path.home() / 'galaxy_s25_avd_backups'
    work = backups / avd / 'setup'
    manifest_path = work / 'setup-complete.json'
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1 or manifest.get('avd') != avd:
        raise ValueError('setup certificate does not match the AVD')
    checks = set(manifest.get('completedChecks') or ())
    required = {'cellular-lte', 'battery-simulation', 'signal-simulation',
                'bounded-gps', 'root-isolation'}
    if not required <= checks:
        raise ValueError('setup certificate does not cover every runtime service')
    location = json.loads((work / 'proxy-location.json').read_text())
    timezone = location.get('timezone')
    latitude, longitude = location.get('latitude'), location.get('longitude')
    if (not isinstance(timezone, str) or type(latitude) not in (int, float) or
            type(longitude) not in (int, float) or not math.isfinite(latitude) or
            not math.isfinite(longitude) or not -90 <= latitude <= 90 or
            not -180 <= longitude <= 180):
        raise ValueError('saved proxy location is invalid')
    ZoneInfo(timezone)
    profile = work / 'profile/device-profile.json'
    if not profile.is_file():
        raise ValueError('saved device profile is missing')
    return dict(avd=avd, work=work, manifest=manifest, location=location,
                timezone=timezone, profile=profile)


def call(command, timeout=30):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                          check=True).stdout.replace('\r', '')


def find_serial(adb, avd):
    for line in call([adb, 'devices']).splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and columns[0].startswith('emulator-') and columns[1] == 'device':
            serial = columns[0]
            name = call([adb, '-s', serial, 'shell', 'getprop', 'ro.boot.qemu.avd_name']).strip()
            if name == avd:
                return serial
    return None


def wait_for_boot(adb, avd, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            serial = find_serial(adb, avd)
            if serial and call([adb, '-s', serial, 'shell', 'getprop', 'sys.boot_completed']).strip() == '1':
                return serial
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise RuntimeError('Android did not complete boot for runtime restoration')


def wait_state(path, avd, serial, timeout=20, center=None, newer_than=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads(path.read_text())
            valid = state.get('avd') == avd and state.get('serial') == serial and state.get('tick', 0) >= 1
            if newer_than is not None:
                valid = valid and path.stat().st_mtime >= newer_than
            if center:
                valid = valid and math.isclose(float(state['center_latitude']), center[0], abs_tol=1e-7) \
                    and math.isclose(float(state['center_longitude']), center[1], abs_tol=1e-7)
            if valid:
                return state
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError(f'Runtime controller did not produce current state: {path}')


def verify_battery(adb, serial, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = call([adb, '-s', serial, 'shell', 'su', '-c',
                        'cat /data/adb/s25-avd-lab/battery.state 2>/dev/null'])
            state = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
            level = call([adb, '-s', serial, 'shell', 'dumpsys', 'battery', 'get', 'level']).strip()
            temp = call([adb, '-s', serial, 'shell', 'dumpsys', 'battery', 'get', 'temp']).strip()
            if state.get('LEVEL') == level and state.get('TEMP') == temp:
                return
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError('persistent battery service did not restore its saved state')


def restore_android_settings(adb, serial, avd, timezone):
    identity_path = avd_directory(avd) / 's25-identifiers.json'
    identity = json.loads(identity_path.read_text())
    if identity.get('avd') != avd:
        raise RuntimeError('saved Android settings belong to another phone')
    settings = identity.get('system_settings')
    if not isinstance(settings, dict) or not settings:
        raise RuntimeError('saved per-phone Android settings are missing')
    for key, value in settings.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError('saved per-phone Android setting is invalid')
        call([adb, '-s', serial, 'shell', 'settings', '--user', '0', 'put',
              'system', key, value])
        observed = call([adb, '-s', serial, 'shell', 'settings', '--user', '0',
                         'get', 'system', key]).strip()
        if observed != value:
            raise RuntimeError(f'Android setting did not persist: {key}')
    call([adb, '-s', serial, 'shell', 'settings', 'put', 'global', 'auto_time_zone', '0'])
    call([adb, '-s', serial, 'shell', 'cmd', 'alarm', 'set-timezone', timezone])
    if call([adb, '-s', serial, 'shell', 'getprop', 'persist.sys.timezone']).strip() != timezone:
        raise RuntimeError('Android timezone does not match the saved proxy timezone')
    call([adb, '-s', serial, 'shell', 'cmd', 'location', 'set-location-enabled', 'true'])
    enabled = call([adb, '-s', serial, 'shell', 'cmd', 'location',
                    'is-location-enabled']).strip()
    if enabled != 'true':
        raise RuntimeError('Android location service did not remain enabled')


def restore(runtime):
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or
               Path.home() / 'Library/Android/sdk')
    adb = shutil.which('adb') or str(sdk / 'platform-tools/adb')
    avd, work = runtime['avd'], runtime['work']
    serial = wait_for_boot(adb, avd)

    restore_android_settings(adb, serial, avd, runtime['timezone'])

    # setup_network imports the sibling setup_ui module, so its script directory
    # must remain on sys.path (isolated mode would remove it).
    call([sys.executable, str(ROOT / 'setup_network.py'), '--serial', serial], timeout=90)
    verify_battery(adb, serial)

    controller_started = time.time()
    signal = subprocess.run([sys.executable, '-I', str(ROOT / 'emulator_signal_sim.py'),
                             '--avd', avd, '--profile', str(runtime['profile']), '--background'],
                            capture_output=True, text=True, timeout=10)
    # A host controller can survive a quick guest reboot. Its lock is valid if
    # it resumes producing fresh state for this exact AVD/serial.
    try:
        wait_state(work / 'profile/radio-state.json', avd, serial,
                   newer_than=controller_started)
    except RuntimeError:
        if signal.returncode:
            raise RuntimeError('signal controller could not be started or resumed')
        raise

    center = (float(runtime['location']['latitude']), float(runtime['location']['longitude']))
    location = subprocess.run([sys.executable, '-I', str(ROOT / 'emulator_location_sim.py'),
                               '--avd', avd, '--output', str(work / 'location'),
                               '--latitude', str(center[0]), '--longitude', str(center[1]), '--background'],
                              capture_output=True, text=True, timeout=10)
    try:
        wait_state(work / 'location/location-state.json', avd, serial, center=center,
                   newer_than=controller_started)
    except RuntimeError:
        if location.returncode:
            raise RuntimeError('GPS controller could not be started or resumed')
        raise

    # Re-check the certified device identity, artifact hashes and app isolation.
    for package in runtime['manifest'].get('authorizedSignupPackages') or ():
        call([sys.executable, '-I', str(ROOT / 'phone_setup_guard.py'), '--verify',
              '--serial', serial, '--avd', avd, '--manifest',
              str(work / 'setup-complete.json'), '--package', package], timeout=60)
    print(json.dumps({'avd': avd, 'serial': serial, 'timezone': runtime['timezone'],
                      'latitude': center[0], 'longitude': center[1],
                      'signal_controller': signal.returncode == 0,
                      'location_controller': location.returncode == 0,
                      'status': 'runtime-restored'}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--backups', type=Path)
    args = parser.parse_args()
    runtime = load_runtime(args.avd, args.backups)
    if runtime is None:
        print('No completed phone certificate; runtime restoration is not required yet.')
        return
    restore(runtime)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        raise SystemExit(f'Phone runtime restoration failed: {error}')
