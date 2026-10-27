#!/usr/bin/env python3
"""Install a supported test app through Google Play, optionally leaving it closed."""
import argparse
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from setup_ui import read_ui
from google_play_signin import ensure_sign_in, play_screen_action

PACKAGE = 'com.bumble.app'
APPS = {
    'bumble': (PACKAGE, 'Bumble', 'Bumble Dating App', 'Bumble'),
    'tinder': ('com.tinder', 'Tinder', 'Tinder', 'Tinder'),
    'pof': ('com.pof.android', 'Plenty of Fish', 'Plenty of Fish', 'POF'),
    'hinge': ('co.hinge.app', 'Hinge', 'Hinge Dating App', 'Hinge'),
    'okcupid': ('com.okcupid.okcupid', 'OkCupid', 'OkCupid', 'OkCupid'),
    'match': ('com.match.android.matchmobile', 'Match', 'Match Dating', 'Match'),
    'eharmony': ('com.eharmony', 'eharmony', 'eharmony', 'eharmony'),
    'coffee-meets-bagel': ('io.cmbus.app', 'Coffee Meets Bagel', 'Coffee Meets Bagel', 'Coffee Meets Bagel'),
    'facebook-dating': ('com.facebook.katana', 'Facebook', 'Facebook', 'Facebook'),
    'feeld': ('co.feeld', 'Feeld', 'Feeld', 'Feeld'),
    'zoosk': ('com.zoosk.zoosk', 'Zoosk', 'Zoosk', 'Zoosk'),
    'badoo': ('com.badoo.mobile', 'Badoo', 'Badoo', 'Badoo'),
    'elitesingles': ('com.elitesingles.dating', 'EliteSingles', 'EliteSingles', 'EliteSingles'),
    'hily': ('com.hily.app', 'Hily', 'Hily Dating', 'Hily'),
    'happn': ('com.ftw_and_co.happn', 'happn', 'happn', 'happn'),
}


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
    parser.add_argument('--app', choices=tuple(APPS), default='bumble')
    parser.add_argument('--avd', help='Require this AVD name before making changes')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--sign-in', action='store_true', help='Handle Google sign-in with private terminal prompts')
    parser.add_argument('--install-only', action='store_true',
                        help='Verify the Play Store installation, force-stop the app, and do not open it')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    package, title, listing_marker, permission_label = APPS[args.app]

    def call(*command):
        return subprocess.run(['adb', '-s', args.serial, *command], capture_output=True,
                              text=True, timeout=15, check=True).stdout

    if args.avd and call('emu', 'avd', 'name').splitlines()[0].strip() != args.avd:
        raise RuntimeError('Connected AVD does not match --avd')
    call('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
         '-d', f'market://details?id={package}', '-p', 'com.android.vending')
    if args.sign_in:
        ensure_sign_in(args.serial, button_center, package=package, listing_marker=listing_marker)
    deadline = time.monotonic() + args.timeout
    requested = False
    last_status = None
    while time.monotonic() < deadline:
        installed = any(line.strip() == f'package:{package}' for line in
                        call('shell', 'pm', 'list', 'packages', package).splitlines())
        xml = read_ui(args.serial)
        if not xml:
            time.sleep(2)
            continue
        screen = play_screen_action(xml)
        if screen == 'agreement':
            control = button_center(xml, 'I agree')
            if not control:
                raise RuntimeError('Google terms screen has no unambiguous I agree control')
            call('shell', 'input', 'tap', *(str(x) for x in control))
            print('Accepted the explicitly authorized Google terms.', flush=True)
            deadline = time.monotonic() + args.timeout
            time.sleep(2)
            continue
        if screen == 'account-setup':
            control = button_center(xml, 'Continue')
            if not control:
                raise RuntimeError('Complete account setup has no unambiguous Continue control')
            call('shell', 'input', 'tap', *(str(x) for x in control))
            # Account setup can interrupt the original Install request.
            requested = False
            print('Continuing Google Play account review; waiting for the next screen.', flush=True)
            time.sleep(2)
            continue
        if screen == 'payment-setup':
            control = button_center(xml, 'Skip')
            if not control:
                raise RuntimeError('Payment setup has no unambiguous Skip control')
            call('shell', 'input', 'tap', *(str(x) for x in control))
            requested = False
            print('Skipped optional Google Play payment setup.', flush=True)
            time.sleep(2)
            continue
        if screen == 'play-pass':
            dismiss = button_center(xml, 'Not now')
            if not dismiss:
                raise RuntimeError('Play Pass offer has no unambiguous Not now control')
            call('shell', 'input', 'tap', *(str(x) for x in dismiss))
            print('Dismissed optional Play Pass subscription offer.', flush=True)
            time.sleep(2)
            continue
        # The target listing is opened directly; never search among similarly named apps.
        if listing_marker not in xml:
            if args.sign_in:
                ensure_sign_in(args.serial, button_center, package=package,
                               listing_marker=listing_marker)
                deadline = time.monotonic() + args.timeout
                continue
            raise RuntimeError(f'{title} listing is not visible; finish Play Store sign-in or prompts manually')
        if installed:
            open_button = button_center(xml, 'Open')
            if open_button:
                source = call('shell', 'pm', 'list', 'packages', '-i', package)
                if not re.search(r'package:' + re.escape(package) + r'\s+installer=com\.android\.vending(?:\s|$)', source):
                    raise RuntimeError(f'{title} is installed but its installer is not Google Play')
                dump = call('shell', 'dumpsys', 'package', package)
                version = re.search(r'^\s*versionName=(\S+)', dump, re.M)
                print(f'{title} {version.group(1) if version else "(version unavailable)"} installed by Google Play.', flush=True)
                if args.install_only:
                    # A package can expose install/replace receivers. Force-stop it so the
                    # first deliberate foreground launch happens only after isolation and
                    # the final device checks have passed.
                    call('shell', 'am', 'force-stop', package)
                    print(f'{title} is installed and held closed for final phone setup.', flush=True)
                    return 0
                call('shell', 'input', 'tap', *(str(x) for x in open_button))
                for _ in range(10):
                    activity = call('shell', 'dumpsys', 'activity', 'activities')
                    if re.search(r'(?:mResumedActivity|topResumedActivity)[^\n]*' + re.escape(package) + '/', activity):
                        print(f'{title} opened and verified in the foreground.', flush=True)
                        return 0
                    if 'permissioncontroller' in activity:
                        permission_ui = read_ui(args.serial)
                        if f'Allow {permission_label} to send you notifications?' in permission_ui:
                            print(f'{title} launched; Android notification permission awaits a choice.', flush=True)
                            return 0
                    time.sleep(1)
                raise RuntimeError(f'Open was tapped but {title} did not reach the foreground')
        if not requested and not installed:
            install_button = button_center(xml, 'Install')
            if install_button:
                call('shell', 'input', 'tap', *(str(x) for x in install_button))
                requested = True
                print('Tapped Play Store Install; waiting for package installation and Open.', flush=True)
        status = 'Waiting for Play Store Open.' if installed else f'Waiting for {title} download and installation.'
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
