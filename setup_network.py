#!/usr/bin/env python3
"""Require an Android-validated LTE cellular default network; keep Wi-Fi off."""
import argparse
import re
import subprocess
import time

from setup_ui import adb_call


def validated_default(dump, transport=None):
    match = re.search(r'^Active default network: (\d+)\s*$', dump, re.MULTILINE)
    if not match:
        return False
    marker = 'network{' + match.group(1) + '}'
    current = dump.split('Current Networks:', 1)[-1].split('Status for known UIDs:', 1)[0]
    return any(marker in line and re.search(r'\bCapabilities: [^\]]*\bVALIDATED\b', line)
               and (transport is None or re.search(r'\bTransports:\s*' + transport + r'\b', line))
               for line in current.splitlines())


def lte_registered(dump):
    return bool(re.search(r'\b(?:mDataConnectionNetworkType|mDataNetworkType)\s*=\s*(?:13\b|LTE\b)', dump)
                or re.search(r'\bmRilDataRadioTechnology\s*=\s*14\b', dump)
                or re.search(r'\b(?:accessNetworkTechnology|getRilDataRadioTechnology)\s*=\s*(?:LTE|EUTRAN)\b', dump))


def ensure_network(serial, timeout=60, call=adb_call, now=time.monotonic, pause=time.sleep):
    deadline = now() + timeout
    call(serial, 'shell', 'svc', 'wifi', 'disable')
    call(serial, 'shell', 'settings', 'put', 'global', 'wifi_scan_always_enabled', '0')
    call(serial, 'shell', 'svc', 'data', 'enable')
    registration = call(serial, 'emu', 'gsm', 'data', 'home')
    if 'KO:' in registration:
        raise RuntimeError('Could not register the simulated cellular data connection')
    requested = False
    while now() < deadline:
        if not requested:
            # Android 15's shell command expects a binary network-type mask.
            try:
                result = call(serial, 'shell', 'cmd', 'phone', 'set-allowed-network-types-for-users',
                              '-s', '0', '1000000000000')
            except subprocess.CalledProcessError:
                result = ''  # SIM subscription can still be initializing after boot.
            requested = 'completed' in result.lower()
        if (requested and validated_default(call(serial, 'shell', 'dumpsys', 'connectivity'), 'CELLULAR')
                and lte_registered(call(serial, 'shell', 'dumpsys', 'telephony.registry'))):
            print('Network: Android reports validated LTE cellular data; Wi-Fi is off.', flush=True)
            return
        pause(2)
    raise RuntimeError('Android has no validated LTE cellular data connection. Wi-Fi fallback is disabled.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    ensure_network(args.serial)


if __name__ == '__main__':
    main()
