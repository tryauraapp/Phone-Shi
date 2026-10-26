#!/usr/bin/env python3
"""Move emulator GPS 20–30 feet every 3–5 seconds within a fixed 1,000-foot circle."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess

_host_spec = importlib.util.spec_from_file_location(
    "_phone_shi_host_platform", Path(__file__).resolve().with_name("host_platform.py"))
_host_module = importlib.util.module_from_spec(_host_spec)
_host_spec.loader.exec_module(_host_module)
android_sdk_root = _host_module.android_sdk_root
import sys
import time

EARTH_FEET = 6371008.8 / 0.3048
RADIUS_FEET = 1000


def distance_feet(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_FEET * math.asin(math.sqrt(min(1, max(0, h))))


def destination(point, feet, bearing):
    lat, lon = map(math.radians, point)
    angle = feet / EARTH_FEET
    new_lat = math.asin(math.sin(lat) * math.cos(angle) + math.cos(lat) * math.sin(angle) * math.cos(bearing))
    new_lon = lon + math.atan2(math.sin(bearing) * math.sin(angle) * math.cos(lat),
                               math.cos(angle) - math.sin(lat) * math.sin(new_lat))
    return math.degrees(new_lat), (math.degrees(new_lon) + 180) % 360 - 180


def next_position(rng, point, center):
    # Reject outward steps near the edge instead of clipping their length.
    for _ in range(100):
        candidate = destination(point, rng.uniform(20, 30), rng.uniform(0, math.tau))
        if distance_feet(center, candidate) <= RADIUS_FEET:
            return candidate
    # An inward bearing provides a bounded fallback even for unlucky RNG draws.
    lat1, lon1, lat2, lon2 = map(math.radians, (*point, *center))
    bearing = math.atan2(math.sin(lon2 - lon1) * math.cos(lat2),
                         math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return destination(point, rng.uniform(20, 30), bearing)


def adb_call(adb, *args):
    result = subprocess.run([adb, *args], capture_output=True, text=True, timeout=15)
    if result.returncode or 'KO:' in result.stdout:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.replace('\r', '')


def find_serial(adb, avd):
    for line in adb_call(adb, 'devices').splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and columns[0].startswith('emulator-') and columns[1] == 'device':
            if adb_call(adb, '-s', columns[0], 'emu', 'avd', 'name').splitlines()[0] == avd:
                return columns[0]
    raise RuntimeError(f'No running emulator for AVD {avd}')


def run_controller(adb, avd, output, center, ticks=None):
    serial = find_serial(adb, avd)
    rng = random.Random()
    point = center
    tick = 0
    while True:
        # A serial can be reused by another AVD after the original disconnects.
        if adb_call(adb, '-s', serial, 'emu', 'avd', 'name').splitlines()[0] != avd:
            raise RuntimeError('AVD identity changed; stopping GPS controller')
        latitude, longitude = point
        adb_call(adb, '-s', serial, 'emu', 'geo', 'fix', str(longitude), str(latitude), '0', '8')
        tick += 1
        state = dict(avd=avd, serial=serial, pid=os.getpid(), latitude=latitude, longitude=longitude,
                     center_latitude=center[0], center_longitude=center[1],
                     distance_feet=distance_feet(center, point), radius_feet=RADIUS_FEET,
                     tick=tick, updated_at=datetime.now(timezone.utc).isoformat())
        temporary = output / 'location-state.tmp'
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(output / 'location-state.json')
        if ticks and tick >= ticks:
            return
        time.sleep(rng.uniform(3, 5))
        point = next_position(rng, point, center)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--latitude', type=float, default=40.7357)
    parser.add_argument('--longitude', type=float, default=-74.1724)
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--ticks', type=int)
    args = parser.parse_args()
    if not (-90 <= args.latitude <= 90 and -180 <= args.longitude <= 180):
        parser.error('Invalid center coordinates')
    if args.ticks is not None and args.ticks < 1:
        parser.error('--ticks must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.background:
        if args.ticks:
            parser.error('--background cannot be combined with --ticks')
        with (args.output / 'location.log').open('a') as log:
            child = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()),
                                      '--avd', args.avd, '--output', str(args.output.resolve()),
                                      '--latitude', str(args.latitude), '--longitude', str(args.longitude)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        time.sleep(1)
        if child.poll() is not None:
            raise RuntimeError('GPS controller exited; inspect location.log')
        print(f'Started GPS controller PID {child.pid}')
        return
    sdk = android_sdk_root()
    adb = shutil.which('adb') or str(sdk / 'platform-tools/adb')
    with (args.output / 'location.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('A GPS controller already owns this output directory')
        run_controller(adb, args.avd, args.output, (args.latitude, args.longitude), args.ticks)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'GPS simulation stopped: {error}')
