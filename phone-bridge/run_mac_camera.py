#!/usr/bin/env python3
"""Launch one existing AVD with its physical FaceTime camera and tested host GPU."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', default='Galaxy_S25_20261027_tinder_f001699c')
    parser.add_argument('--restart', action='store_true', help='Restart only this AVD to apply the camera/GPU options')
    args = parser.parse_args()
    sdk = Path.home() / 'Library/Android/sdk'
    result = subprocess.run([str(sdk / 'emulator/emulator'), '-webcam-list'],
                            capture_output=True, text=True, check=True, timeout=20)
    matches = re.findall(r"Camera 'FaceTime HD Camera' can be specified by label as '(webcam\d+)'", result.stdout + result.stderr)
    if len(matches) != 1:
        parser.error('Exactly one physical FaceTime HD Camera must be available; no alternate camera will be substituted.')
    spec = importlib.util.spec_from_file_location('native_video_camera', root / 'native_video_camera.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    adb = str(sdk / 'platform-tools/adb')
    serial = native.running_serial(args.avd, adb)
    if serial:
        if not args.restart:
            print(f'{args.avd} is already running as {serial}. Use --restart only when applying the direct-camera options.')
            return 0
        subprocess.run([adb, '-s', serial, 'emu', 'kill'], check=True, timeout=10)
        for attempt in range(40):
            if native.running_serial(args.avd, adb) is None:
                # ADB can disconnect before the emulator releases its AVD lock.
                time.sleep(2)
                break
            time.sleep(.5)
        else:
            parser.error('The selected AVD did not shut down; refusing to launch a duplicate.')
    print(f'Using physical FaceTime HD Camera ({matches[0]}) and host GPU for {args.avd}.', flush=True)
    return subprocess.call([sys.executable, str(root / 'emulator_proxy.py'), '--avd', args.avd,
                            '-camera-front', matches[0], '-gpu', 'host'])


if __name__ == '__main__':
    raise SystemExit(main())
