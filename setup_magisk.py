#!/usr/bin/env python3
"""Confirm Magisk setup and verify its result, retrying unaccepted UI actions."""
import argparse
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_ui import adb_call, read_ui, setup_ok_center


class DeviceStateUnavailable(RuntimeError):
    pass


def state(serial, call):
    lines = call(serial, 'shell',
                 'cat /proc/sys/kernel/random/boot_id; getprop sys.boot_completed; '
                 'if [ -x /system_ext/bin/su ] || [ -x /system/bin/su ] || '
                 '[ -x /system/xbin/su ]; then echo ready; else echo incomplete; fi; '
                 'getprop ro.boot.qemu.avd_name').strip().splitlines()
    if len(lines) != 4:
        raise DeviceStateUnavailable('Incomplete device state during reboot')
    return tuple(line.strip() for line in lines)


def complete_setup(serial, avd, timeout=240, call=adb_call, read=read_ui,
                   now=time.monotonic, pause=time.sleep):
    initial, _, _, identity = state(serial, call)
    if identity != avd:
        raise RuntimeError('Emulator identity changed; refusing to continue')
    deadline = now() + timeout
    last_open = last_tap = -1000
    taps = 0
    accepted = False
    while now() < deadline:
        try:
            boot, completed, environment, identity = state(serial, call)
            if identity != avd:
                raise RuntimeError('Emulator identity changed; refusing to continue')
            if completed == '1' and environment == 'ready':
                if boot != initial or taps == 0:
                    print('Magisk environment complete; Android boot and su mount verified.', flush=True)
                    return
            if completed != '1' or boot != initial:
                pause(2)
                continue
            xml = read(serial, call=call, pause=pause)
            if not xml:
                pause(2)
                continue
            center = setup_ok_center(xml)
            if center and now() - last_tap >= 5:
                if taps >= 4:
                    raise RuntimeError('Magisk setup confirmation remained visible after four attempts')
                call(serial, 'shell', 'input', 'tap', str(center[0]), str(center[1]))
                taps += 1
                last_tap = now()
                print(f'Magisk setup: OK sent (attempt {taps}); verifying acceptance.', flush=True)
                accepted = False
            elif not center:
                if taps and not accepted:
                    print('Magisk setup dialog closed; waiting for reboot and environment verification.', flush=True)
                    accepted = True
                # Recover from returning to the launcher without rebooting.
                if now() - last_open >= 20 and now() - last_tap >= 15:
                    call(serial, 'shell', 'monkey', '-p', 'com.topjohnwu.magisk',
                         '-c', 'android.intent.category.LAUNCHER', '1')
                    last_open = now()
            pause(2)
        except (DeviceStateUnavailable, subprocess.SubprocessError, OSError) as error:
            print(f'Magisk setup: transient device/UI error: {error}', file=sys.stderr, flush=True)
            pause(2)
    raise RuntimeError('Magisk setup timed out; no verified completed environment after confirmation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    try:
        complete_setup(args.serial, args.avd, args.timeout)
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
