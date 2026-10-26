#!/usr/bin/env python3
"""Stop only the host controller that owns a selected phone's runtime lock."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def stop_controller(avd, state_path, lock_path, script, owner_flag, owner_path, timeout=20):
    # A released lock proves termination even if the old PID is a zombie or
    # has since been reused. Never signal a PID from a stale state file alone.
    if not lock_path.exists():
        return
    with lock_path.open('a+') as lock:
        def released():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False

        if released():
            return
        state = json.loads(state_path.read_text())
        pid = state.get('pid')
        if state.get('avd') != avd or type(pid) is not int or pid <= 1:
            raise RuntimeError('Controller state does not identify this phone and a usable PID')
        result = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            if released():
                return
            raise RuntimeError('Controller lock is held but its recorded process cannot be identified')
        # ps renders argv with spaces rather than shell quoting. These detached
        # controllers use this exact argument order, including paths with spaces.
        expected = f' {script.resolve()} --avd {avd} {owner_flag} {owner_path.resolve()}'
        command = result.stdout.strip() + ' '
        if expected + ' ' not in command:
            raise RuntimeError('Controller PID belongs to another process; refusing to stop it')
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if released():
                print(f'Stopped {script.stem} for {avd}.', flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError(f'{script.stem} did not release its runtime lock after stopping')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--kind', choices=('signal', 'location'), required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    root = Path(__file__).resolve().parent
    if args.kind == 'signal':
        profile = work / 'profile/device-profile.json'
        stop_controller(args.avd, work / 'profile/radio-state.json',
                        profile.with_suffix('.radio.lock'), root / 'emulator_signal_sim.py',
                        '--profile', profile)
    else:
        output = work / 'location'
        stop_controller(args.avd, output / 'location-state.json', output / 'location.lock',
                        root / 'emulator_location_sim.py', '--output', output)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Controller shutdown: {error}')
