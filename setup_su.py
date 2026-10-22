#!/usr/bin/env python3
"""Verify a newly granted shell policy without perpetuating Magisk's cache."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_ui import adb_call


def wait_for_root(serial, timeout=30, call=adb_call, now=time.monotonic, pause=time.sleep):
    deadline = now() + timeout
    # Magisk v30.6 caches SuInfo for three seconds and refreshes its timestamp
    # on every request, including denials. Never poll inside that interval.
    while now() + 4 < deadline:
        pause(4)
        try:
            if call(serial, 'shell', 'su -c "id -u"').strip() == '0':
                return True
        except (subprocess.SubprocessError, OSError):
            pass
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    if wait_for_root(args.serial, args.timeout):
        print('Shell root verified (UID 0) after allowing the permission cache to expire.')
        return 0
    print('Shell root did not become available after spaced verification attempts.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
