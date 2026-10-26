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


def ensure_first_boot_network(serial, avd, timeout=60, boot_timeout=360,
                              call=adb_call, now=time.monotonic, pause=time.sleep):
    """Retry a fresh phone once after reboot if first-boot SIM setup stalls."""
    def verify_avd():
        if call(serial, 'emu', 'avd', 'name').splitlines()[0].strip() != avd:
            raise RuntimeError('Network recovery AVD does not match the selected phone')

    verify_avd()
    try:
        ensure_network(serial, timeout, call, now, pause)
        return
    except RuntimeError:
        # Preserve the failure in the setup log without dumping SIM identifiers.
        dump = call(serial, 'shell', 'dumpsys', 'connectivity')
        default = re.search(r'^Active default network: (.*)$', dump, re.MULTILINE)
        print('First-boot LTE check failed; active default network: '
              + (default.group(1) if default else 'unavailable'), flush=True)
    verify_avd()
    old_boot = call(serial, 'shell', 'cat', '/proc/sys/kernel/random/boot_id').strip()
    if not old_boot:
        raise RuntimeError('Cannot confirm boot identity before network recovery')
    print('Rebooting this new phone once to retry SIM/carrier initialization.', flush=True)
    call(serial, 'reboot')
    deadline = now() + boot_timeout
    reconnect_at = now() + 20
    while now() < deadline:
        try:
            boot = call(serial, 'shell', 'cat', '/proc/sys/kernel/random/boot_id').strip()
            if boot and boot != old_boot and call(serial, 'shell', 'getprop', 'sys.boot_completed').strip() == '1':
                break
        except subprocess.SubprocessError:
            # Only reconnect the selected transport, never restart the shared adb server.
            if now() >= reconnect_at:
                try:
                    call(serial, 'reconnect')
                except subprocess.SubprocessError:
                    pass
                reconnect_at = now() + 20
        pause(2)
    else:
        raise RuntimeError('First-boot network recovery reboot did not finish; phone data is retained')
    verify_avd()
    ensure_network(serial, timeout, call, now, pause)


def ensure_isolation_network(serial, avd, timeout=60, call=adb_call,
                             now=time.monotonic, pause=time.sleep):
    """Recover the observed radio callback failure after the isolation reboot."""
    def verify_avd():
        if call(serial, 'emu', 'avd', 'name').splitlines()[0].strip() != avd:
            raise RuntimeError('Radio recovery AVD does not match the selected phone')

    verify_avd()
    try:
        ensure_network(serial, timeout, call, now, pause)
        return
    except RuntimeError:
        # This is a missing HAL callback, not a slow download or a proxy error.
        # Only apply the restart when the SIM is not loaded and the radio log
        # contains the failure observed on this emulator image.
        sim = call(serial, 'shell', 'getprop', 'gsm.sim.state').strip()
        radio = call(serial, 'shell', 'su', '-c', 'logcat -b radio -d -t 200')
        if sim == 'LOADED' or 'mRadioIndication == NULL' not in radio:
            raise
    verify_avd()
    print('Radio callbacks are missing after isolation; restarting vendor.ril-daemon once.', flush=True)
    call(serial, 'shell', 'su', '-c', 'setprop ctl.restart vendor.ril-daemon')
    ensure_network(serial, timeout, call, now, pause)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument('--recover-first-boot', action='store_true')
    recovery.add_argument('--recover-radio', action='store_true')
    parser.add_argument('--avd', help='Required identity check before first-boot recovery')
    args = parser.parse_args()
    if args.recover_first_boot or args.recover_radio:
        if not args.avd:
            parser.error('Network recovery requires --avd')
        recover = ensure_first_boot_network if args.recover_first_boot else ensure_isolation_network
        recover(args.serial, args.avd)
    else:
        ensure_network(args.serial)


if __name__ == '__main__':
    main()
