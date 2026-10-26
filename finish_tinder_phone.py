#!/usr/bin/env python3
"""Finish a retained Tinder phone after Google Play installation paused setup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import phone_setup_guard
import restore_phone_runtime


ROOT = Path(__file__).resolve().parent


def run(command, *, timeout=60, input_text=None, check=True):
    return subprocess.run(command, input=input_text, capture_output=True, text=True,
                          timeout=timeout, check=check)


def adb(serial, *arguments, timeout=60, check=True, input_text=None):
    return run(['adb', '-s', serial, *arguments], timeout=timeout, check=check,
               input_text=input_text)


def root(serial, script, timeout=60):
    return adb(serial, 'shell', 'su', timeout=timeout, input_text=script + '\n')


def wait_boot(serial, avd, timeout=420):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            name = adb(serial, 'shell', 'getprop', 'ro.boot.qemu.avd_name', timeout=10).stdout.strip()
            booted = adb(serial, 'shell', 'getprop', 'sys.boot_completed', timeout=10).stdout.strip()
            if name == avd and booted == '1':
                return
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise RuntimeError('Android did not return after the isolation reboot')


def wait_old_controllers(pids, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        living = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                living.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
        if not living:
            return
        time.sleep(1)
    raise RuntimeError('old host runtime controllers did not stop across reboot')


def state_pid(path):
    try:
        return int(json.loads(path.read_text()).get('pid'))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--work', type=Path)
    args = parser.parse_args()
    work = (args.work or Path.home() / 'galaxy_s25_avd_backups' / args.avd / 'setup').resolve()
    location = json.loads((work / 'proxy-location.json').read_text())
    profile = work / 'profile/device-profile.json'
    if adb(args.serial, 'shell', 'getprop', 'ro.boot.qemu.avd_name').stdout.strip() != args.avd:
        raise RuntimeError('connected emulator does not match --avd')
    if not adb(args.serial, 'shell', 'pm', 'path', 'com.tinder').stdout.startswith('package:'):
        raise RuntimeError('Tinder is not installed')
    if root(args.serial, 'id -u').stdout.strip() != '0':
        raise RuntimeError('shell root is unavailable')

    print('Configuring Magisk isolation for Tinder and the checker…', flush=True)
    adb(args.serial, 'push', str(ROOT / 'device_root_isolation.sh'),
        '/data/local/tmp/s25-root-isolation.sh')
    for package in ('com.tinder', 'dev.emulab.devicecheck'):
        root(args.serial, f'sh /data/local/tmp/s25-root-isolation.sh {package}')
    adb(args.serial, 'shell', 'rm', '-f', '/data/local/tmp/s25-root-isolation.sh')

    old_pids = [pid for pid in (
        state_pid(work / 'profile/radio-state.json'),
        state_pid(work / 'location/location-state.json')) if pid]
    print('Rebooting once to activate isolation…', flush=True)
    adb(args.serial, 'reboot')
    time.sleep(3)
    wait_boot(args.serial, args.avd)
    wait_old_controllers(old_pids)

    run([sys.executable, str(ROOT / 'setup_network.py'), '--serial', args.serial], timeout=120)
    # The Magisk network service pins the reserved Wi-Fi MAC even though Wi-Fi
    # stays disabled; run it after this activation reboot before identity read-back.
    root(args.serial, 'sh /data/adb/service.d/96-s25-network.sh')
    restore_phone_runtime.restore_android_settings(
        'adb', args.serial, args.avd, location['timezone'])
    result = adb(args.serial, 'emu', 'geo', 'fix', str(location['longitude']),
                 str(location['latitude']), '0', '8').stdout
    if 'OK' not in result or 'KO:' in result:
        raise RuntimeError('proxy-derived GPS could not be restored')
    run([sys.executable, '-I', str(ROOT / 'device_identifiers.py'), '--avd-dir',
         str(restore_phone_runtime.avd_directory(args.avd)), '--verify-serial', args.serial,
         '--adb', 'adb'], timeout=90)
    run([sys.executable, '-I', str(ROOT / 'setup_su.py'), '--serial', args.serial,
         '--avd', args.avd, '--verify-only', '--timeout', '42'], timeout=60)

    started = time.time()
    run([sys.executable, '-I', str(ROOT / 'emulator_signal_sim.py'), '--avd', args.avd,
         '--profile', str(profile), '--background'], timeout=15)
    restore_phone_runtime.wait_state(work / 'profile/radio-state.json', args.avd,
                                     args.serial, newer_than=started)
    run([sys.executable, '-I', str(ROOT / 'emulator_location_sim.py'), '--avd', args.avd,
         '--output', str(work / 'location'), '--latitude', str(location['latitude']),
         '--longitude', str(location['longitude']), '--background'], timeout=15)
    restore_phone_runtime.wait_state(
        work / 'location/location-state.json', args.avd, args.serial,
        center=(float(location['latitude']), float(location['longitude'])), newer_than=started)
    restore_phone_runtime.verify_battery('adb', args.serial)
    print('LTE, settings, battery, signal, GPS and identifiers verified.', flush=True)

    # Remove only the manager UI; the daemon and boot services remain installed.
    packages = adb(args.serial, 'shell', 'pm', 'list', 'packages', 'com.topjohnwu.magisk').stdout
    if 'package:com.topjohnwu.magisk' in packages:
        removed = adb(args.serial, 'shell', 'cmd', 'package', 'uninstall', '-k',
                      'com.topjohnwu.magisk').stdout.strip()
        if removed != 'Success':
            raise RuntimeError('Magisk manager UI could not be removed')
        if root(args.serial, 'id -u').stdout.strip() != '0':
            raise RuntimeError('root daemon did not survive manager removal')

    print('Running the final app-visible checker…', flush=True)
    report = work / 'checker-report.json'
    adb(args.serial, 'shell', 'am', 'force-stop', 'dev.emulab.devicecheck')
    adb(args.serial, 'shell', 'rm', '-f',
        '/sdcard/Android/data/dev.emulab.devicecheck/files/latest-report.json')
    adb(args.serial, 'shell', 'am', 'start', '-W', '-n',
        'dev.emulab.devicecheck/.MainActivity', timeout=30)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        pulled = adb(args.serial, 'pull',
                     '/sdcard/Android/data/dev.emulab.devicecheck/files/latest-report.json',
                     str(report), timeout=20, check=False)
        if pulled.returncode == 0 and report.is_file():
            try:
                phone_setup_guard._validate_checker(report)
                break
            except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
                pass
        time.sleep(2)
    else:
        raise RuntimeError('final checker did not produce an acceptable report')

    adb(args.serial, 'shell', 'am', 'force-stop', 'com.tinder')
    certificate = phone_setup_guard.record_phone_setup(
        args.serial, args.avd, work, ['com.tinder'])
    print(f'Certified completed Tinder phone: {certificate}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        raise SystemExit(f'Tinder phone completion failed: {error}')
