#!/usr/bin/env python3
"""Complete the observed Google Play sign-in flow using private terminal prompts."""
import getpass
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from setup_ui import read_ui


def play_screen_action(xml):
    """Observed overlays take priority over the Bumble listing behind them."""
    nodes = list(ET.fromstring(xml).iter('node'))
    texts = ' '.join(n.get('text', '') for n in nodes).replace('\u00a0', ' ')
    store_texts = ' '.join(n.get('text', '') for n in nodes
                          if n.get('package') == 'com.android.vending').replace('\u00a0', ' ')
    if 'Google Terms of Service' in texts and 'I agree' in texts:
        return 'agreement'
    if ('Complete account setup' in store_texts and
            'Review your account to continue installing apps on Google Play' in store_texts):
        return 'account-setup'
    if ('Complete account setup' in store_texts and
            'Add a payment option to complete your account' in store_texts and
            'Skip' in store_texts):
        return 'payment-setup'
    if 'Try Google Play Pass' in store_texts:
        return 'play-pass'
    return None


def sign_in_action(xml, listing_marker='Bumble Dating App'):
    """Recognize only the observed account screens, preserving manual security checks."""
    tree = ET.fromstring(xml)
    texts = {n.get('text', '') for n in tree.iter('node')}
    overlay = play_screen_action(xml)
    if overlay:
        return overlay
    if 'Protecting your account' in texts and any('Please solve this puzzle' in t for t in texts):
        return 'captcha'
    if 'Welcome to Google Play' in texts and 'Get started' in texts:
        return 'store-welcome'
    if 'What are you into?' in texts and 'Choose apps categories' in texts and 'Skip' in texts:
        return 'store-recommendations'
    if any(listing_marker in text for text in texts):
        return 'done'
    if any(n.get('package') == 'com.android.vending'
           and n.get('content-desc', '').startswith('Signed in as ')
           and 'Account and settings.' in n.get('content-desc', '') for n in tree.iter('node')):
        return 'store-home'
    if 'Sign in with ease' in texts:
        return 'carrier-discovery'
    if 'Google services' in texts:
        return 'services'
    if 'Set a home address' in texts:
        return 'address'
    if 'Make sure you can always sign in' in texts:
        return 'recovery'
    if 'Who will be using this device?' in texts:
        return 'personal'
    if 'I agree' in texts and 'Google Terms of Service' in texts:
        return 'agreement'
    if any('Sign in to find the latest Android apps' in text for text in texts):
        return 'start'
    # Error and additional verification screens stay manual, even with an entry field.
    if any(marker in xml for marker in ('Wrong password', 'Couldn’t find your Google Account',
                                       'Verify it’s you', '2-Step Verification', 'Verify your identity')):
        return 'manual'
    fields = [n for n in tree.iter('node') if n.get('class') == 'android.widget.EditText']
    if len(fields) == 1 and fields[0].get('password') == 'true':
        return 'password'
    if (len(fields) == 1 and 'Forgot email?' in texts
            and (fields[0].get('resource-id') == 'identifierId'
                 or 'Sign in - Google Accounts' in texts or 'Sign in' in texts)):
        return 'email'
    if not texts.difference({'', 'Loading', 'Checking info…', 'Sign in - Google Accounts'}):
        return 'wait'
    return 'manual'


def ensure_sign_in(serial, button_center, timeout=120, package='com.bumble.app',
                   listing_marker='Bumble Dating App'):
    if not sys.stdin.isatty():
        raise RuntimeError('Google sign-in requires an interactive terminal')

    def call(*args, **kwargs):
        return subprocess.run(['adb', '-s', serial, *args], capture_output=True,
                              text=True, timeout=15, check=True, **kwargs).stdout

    def tap(node):
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not bounds:
            raise RuntimeError('Google sign-in control has no usable bounds')
        left, top, right, bottom = map(int, bounds.groups())
        call('shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2))

    def click(xml, label):
        center = button_center(xml, label) or button_center(xml, label.upper())
        if not center:
            raise RuntimeError(f'Google sign-in: expected {label} control is missing')
        call('shell', 'input', 'tap', *(str(value) for value in center))

    submitted = set()
    unknown_screen = None
    unknown_since = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        xml = read_ui(serial)
        if not xml:
            time.sleep(2)
            continue
        action = sign_in_action(xml, listing_marker)
        if action == 'manual':
            # WebView can expose half-rendered pages briefly between known steps.
            # Wait for a stable screen before asking for manual intervention.
            signature = tuple((n.get('text', ''), n.get('content-desc', ''), n.get('class', ''))
                              for n in ET.fromstring(xml).iter('node'))
            if signature != unknown_screen:
                unknown_screen, unknown_since = signature, time.monotonic()
            if time.monotonic() - unknown_since < 6:
                time.sleep(2)
                continue
        else:
            unknown_screen = None
        if action == 'done':
            print('Google Play is ready on the requested app listing.', flush=True)
            return
        tree = ET.fromstring(xml)
        if action in ('email', 'password') and action not in submitted:
            value = getpass.getpass(f'Google {action} (hidden; not saved; or finish on phone and press Enter): ')
            if not value:
                # A human may have completed sign-in on-device while this
                # private terminal prompt was waiting. Never submit stale UI.
                if sign_in_action(read_ui(serial)) != action:
                    deadline = time.monotonic() + timeout
                    continue
                raise RuntimeError('Google sign-in stopped: no credential supplied')
            if not value.isascii() or '%s' in value or '\n' in value or '\r' in value:
                raise RuntimeError('This credential needs manual keyboard entry on the device')
            field = next(n for n in tree.iter('node') if n.get('class') == 'android.widget.EditText')
            tap(field)
            call('shell', 'input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
            call('shell', 'input', 'keyevent', 'KEYCODE_DEL')
            # Pass credentials through stdin, never in host process arguments or log files.
            call('shell', input='input text ' + shlex.quote(value.replace(' ', '%s')) + '\n')
            value = ''
            click(read_ui(serial), 'Next')
            submitted.add(action)
            deadline = time.monotonic() + timeout
        elif action == 'start':
            click(xml, 'Sign in')
        elif action == 'carrier-discovery':
            click(xml, 'SKIP')
            print('Skipped optional carrier-based account discovery.', flush=True)
        elif action == 'store-home':
            call('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
                 '-d', f'market://details?id={package}', '-p', 'com.android.vending')
        elif action == 'store-welcome':
            click(xml, 'Get started')
        elif action == 'store-recommendations':
            click(xml, 'Skip')
        elif action == 'personal':
            controls = [n for n in tree.iter('node') if n.get('text') == 'I will be using this device'
                        and n.get('class') == 'android.widget.RadioButton']
            if len(controls) != 1:
                raise RuntimeError('Expected one personal-use option')
            tap(controls[0])
            click(read_ui(serial), 'Next')
        elif action == 'agreement':
            click(xml, 'I agree')
            print('Accepted the explicitly authorized Google terms.', flush=True)
            deadline = time.monotonic() + timeout
        elif action == 'account-setup':
            click(xml, 'Continue')
        elif action == 'payment-setup':
            click(xml, 'Skip')
            print('Skipped optional Google Play payment setup.', flush=True)
        elif action == 'play-pass':
            click(xml, 'Not now')
        elif action == 'recovery':
            click(xml, 'Cancel')
        elif action == 'address':
            click(xml, 'Skip')
        elif action == 'services':
            switches = [n for n in tree.iter('node') if n.get('checkable') == 'true']
            if 'Use basic device backup' in xml and len(switches) == 1 and switches[0].get('checked') == 'true':
                tap(switches[0])
                xml = read_ui(serial)
            label = 'MORE' if button_center(xml, 'MORE') else 'ACCEPT'
            click(xml, label)
            if label == 'ACCEPT':
                time.sleep(3)
                call('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
                     '-d', f'market://details?id={package}', '-p', 'com.android.vending')
        elif action in ('manual', 'captcha'):
            answer = input(('Complete the CAPTCHA yourself on the device, ' if action == 'captcha' else
                            'Complete the Google security check or unfamiliar screen on the device, ')
                           +
                           'then press Enter (/quit to pause): ')
            if answer.strip() == '/quit':
                raise RuntimeError('Google sign-in paused; the device is retained')
            deadline = time.monotonic() + timeout
        time.sleep(2)
    raise RuntimeError('Google sign-in did not finish; complete it on the device and resume')
