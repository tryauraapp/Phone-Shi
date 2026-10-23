#!/usr/bin/env python3
"""Install Bumble through Google Play, then open it."""
import argparse
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from setup_ui import read_ui
from google_play_signin import ensure_sign_in

PACKAGE = 'com.bumble.app'


def button_center(xml, label):
    tree = ET.fromstring(xml)
    parents = {child: parent for parent in tree.iter() for child in parent}
    targets = set()
    for node in tree.iter('node'):
        if label not in (node.get('text'), node.get('content-desc')):
            continue
        if node.get('enabled') != 'true':
            continue
        target = node
        while target.get('clickable') != 'true' and target in parents:
            target = parents[target]
        if target.get('clickable') != 'true' or target.get('enabled') != 'true':
            continue
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', target.get('bounds', ''))
        if bounds:
            left, top, right, bottom = map(int, bounds.groups())
            if right > left and bottom > top:
                targets.add(((left + right) // 2, (top + bottom) // 2))
    if len(targets) > 1:
        raise RuntimeError(f'Multiple {label} controls; inspect Play Store manually')
    return next(iter(targets), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', help='Require this AVD name before making changes')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--sign-in', action='store_true', help='Handle Google sign-in with private terminal prompts')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')

    def call(*command):
        return subprocess.run(['adb', '-s', args.serial, *command], capture_output=True,
                              text=True, timeout=15, check=True).stdout

    if args.avd and call('emu', 'avd', 'name').splitlines()[0].strip() != args.avd:
        raise RuntimeError('Connected AVD does not match --avd')
    call('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
         '-d', f'market://details?id={PACKAGE}', '-p', 'com.android.vending')
    if args.sign_in:
        ensure_sign_in(args.serial, button_center)
    deadline = time.monotonic() + args.timeout
    requested = False
    last_status = None
    while time.monotonic() < deadline:
        installed = any(line.strip() == f'package:{PACKAGE}' for line in
                        call('shell', 'pm', 'list', 'packages', PACKAGE).splitlines())
        xml = read_ui(args.serial)
        if not xml:
            time.sleep(2)
            continue
        if 'Try Google Play Pass' in xml.replace('\u00a0', ' '):
            dismiss = button_center(xml, 'Not now')
            if not dismiss:
                raise RuntimeError('Play Pass offer has no unambiguous Not now control')
            call('shell', 'input', 'tap', *(str(x) for x in dismiss))
            print('Dismissed optional Play Pass subscription offer.', flush=True)
            time.sleep(2)
            continue
        # The target listing is opened directly; never search among similarly named apps.
        if 'Bumble Dating App' not in xml:
            if args.sign_in:
                ensure_sign_in(args.serial, button_center)
                deadline = time.monotonic() + args.timeout
                continue
            raise RuntimeError('Bumble listing is not visible; finish Play Store sign-in or prompts manually')
        if installed:
            open_button = button_center(xml, 'Open')
            if open_button:
                source = call('shell', 'pm', 'list', 'packages', '-i', PACKAGE)
                if not re.search(r'package:com\.bumble\.app\s+installer=com\.android\.vending(?:\s|$)', source):
                    raise RuntimeError('Bumble is installed but its installer is not Google Play')
                dump = call('shell', 'dumpsys', 'package', PACKAGE)
                version = re.search(r'^\s*versionName=(\S+)', dump, re.M)
                print(f'Bumble {version.group(1) if version else "(version unavailable)"} installed by Google Play.', flush=True)
                call('shell', 'input', 'tap', *(str(x) for x in open_button))
                for _ in range(10):
                    activity = call('shell', 'dumpsys', 'activity', 'activities')
                    if re.search(r'(?:mResumedActivity|topResumedActivity)[^\n]*com\.bumble\.app/', activity):
                        print('Bumble opened and verified in the foreground.', flush=True)
                        return 0
                    time.sleep(1)
                raise RuntimeError('Open was tapped but Bumble did not reach the foreground')
        if not requested and not installed:
            install_button = button_center(xml, 'Install')
            if install_button:
                call('shell', 'input', 'tap', *(str(x) for x in install_button))
                requested = True
                print('Tapped Play Store Install; waiting for package installation and Open.', flush=True)
        status = 'Waiting for Play Store Open.' if installed else 'Waiting for Bumble download and installation.'
        if status != last_status:
            print(status, flush=True)
            last_status = status
        time.sleep(3)
    raise RuntimeError('Timed out waiting for Play Store installation; inspect the device before retrying')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print('\nPlay Store paused; the device and sign-in progress are retained.')
        raise SystemExit(2)
    except (RuntimeError, subprocess.SubprocessError, ET.ParseError) as error:
        raise SystemExit(f'Play Store: {error}')
