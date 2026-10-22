#!/usr/bin/env python3
"""Require Android-validated internet, connecting the emulator Wi-Fi if needed."""
import argparse
import re
import time

from setup_ui import adb_call


def validated_default(dump):
    match = re.search(r'^Active default network: (\d+)\s*$', dump, re.MULTILINE)
    if not match:
        return False
    marker = 'network{' + match.group(1) + '}'
    current = dump.split('Current Networks:', 1)[-1].split('Status for known UIDs:', 1)[0]
    return any(marker in line and re.search(r'\bCapabilities: [^\]]*\bVALIDATED\b', line)
               for line in current.splitlines())


def ensure_network(serial, timeout=60, call=adb_call, now=time.monotonic, pause=time.sleep):
    deadline = now() + timeout
    if validated_default(call(serial, 'shell', 'dumpsys', 'connectivity')):
        return
    print('Network: no validated internet; connecting emulator AndroidWifi.', flush=True)
    call(serial, 'shell', 'svc', 'wifi', 'enable')
    call(serial, 'shell', 'cmd', 'wifi', 'start-scan')
    requested = False
    while now() < deadline:
        if validated_default(call(serial, 'shell', 'dumpsys', 'connectivity')):
            print('Network: Android reports validated internet.', flush=True)
            return
        if not requested:
            scan = call(serial, 'shell', 'cmd', 'wifi', 'list-scan-results')
            # Only the emulator's built-in open AP; never choose arbitrary Wi-Fi.
            if any(re.search(r'\sAndroidWifi\s+\[ESS\]\s*$', line) for line in scan.splitlines()):
                call(serial, 'shell', 'cmd', 'wifi', 'connect-network', 'AndroidWifi', 'open')
                requested = True
        pause(2)
    raise RuntimeError('Android has no validated internet. Check emulator Wi-Fi and the host connection.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    ensure_network(args.serial)


if __name__ == '__main__':
    main()
