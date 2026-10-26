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


class PlayStoreRecovery:
    """Reopen a crashed store without treating Google verification as a crash."""
    def __init__(self, call, package):
        self.call = call
        self.package = package
        self.attempts = 0

    def recover(self, xml):
        launchers = {'com.google.android.apps.nexuslauncher', 'com.android.launcher3'}
        close = None
        if xml:
            nodes = list(ET.fromstring(xml).iter('node'))
            packages = {n.get('package') for n in nodes}
            crash = any(n.get('package') == 'android' and
                        n.get('resource-id') == 'android:id/aerr_close' for n in nodes)
            store_crash = crash and any('Google Play Store' in n.get('text', '') for n in nodes)
            if store_crash:
                close = next(n for n in nodes if n.get('resource-id') == 'android:id/aerr_close')
            elif (not packages.intersection(launchers) or
                  packages.intersection({'com.android.vending', 'com.google.android.gms',
                                         'com.google.android.gsf.login'})):
                return False
        else:
            # UI dumping can fail just as an app dies. Confirm the launcher is
            # resumed before recovery; disconnected devices and security pages
            # must not trigger blind restarts.
            activity = self.call('shell', 'dumpsys', 'activity', 'activities')
            if not re.search(r'(?:mResumedActivity|topResumedActivity)[^\n]*(?:'
                             + '|'.join(re.escape(p) for p in launchers) + r')/', activity):
                return False
        if self.attempts >= 3:
            raise RuntimeError('Google Play crashed or closed repeatedly; stopped after three reopen attempts')
        if close is not None:
            bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', close.get('bounds', ''))
            if not bounds or close.get('enabled') != 'true':
                raise RuntimeError('Play Store crash dialog has no usable Close app control')
            left, top, right, bottom = map(int, bounds.groups())
            self.call('shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2))
        self.call('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
                  '-d', f'market://details?id={self.package}', '-p', 'com.android.vending')
        self.attempts += 1
        print(f'Google Play closed; reopened requested listing (recovery {self.attempts}/3).', flush=True)
        time.sleep(2)
        return True


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
    if (any('Sign in to find the latest Android apps' in text for text in texts)
            or (not any(n.get('class') == 'android.widget.EditText' for n in tree.iter('node'))
                and any(n.get('package') == 'com.android.vending'
                        and n.get('text', '').casefold() == 'sign in' for n in tree.iter('node'))
                and any('Google Play' in text for text in texts))):
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
                   listing_marker='Bumble Dating App', recovery=None):
    def require_terminal():
        if not sys.stdin.isatty():
            raise RuntimeError('Google sign-in requires an interactive terminal for credentials or manual checks')

    def call(*args, **kwargs):
        return subprocess.run(['adb', '-s', serial, *args], capture_output=True,
                              text=True, timeout=15, check=True, **kwargs).stdout

    recovery = recovery or PlayStoreRecovery(call, package)

    def read_screen():
        try:
            return read_ui(serial)
        except subprocess.SubprocessError:
            if recovery.recover(None):
                submitted.clear()
                return ''
            raise

    def tap(node):
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not bounds:
            raise RuntimeError('Google sign-in control has no usable bounds')
        left, top, right, bottom = map(int, bounds.groups())
        call('shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2))

    def click(xml, label):
        if not xml:
            return False
        center = button_center(xml, label) or button_center(xml, label.upper())
        if not center:
            if recovery.recover(xml):
                submitted.clear()
                return False
            raise RuntimeError(f'Google sign-in: expected {label} control is missing')
        call('shell', 'input', 'tap', *(str(value) for value in center))
        return True

    submitted = set()
    sign_in_attempts = 0
    unknown_screen = None
    unknown_since = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        xml = read_screen()
        if not xml:
            time.sleep(2)
            continue
        if recovery.recover(xml):
            submitted.clear()
            unknown_screen = None
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
            require_terminal()
            value = getpass.getpass(f'Google {action} (hidden; not saved; or finish on phone and press Enter): ')
            if not value:
                # A human may have completed sign-in on-device while this
                # private terminal prompt was waiting. Never submit stale UI.
                refreshed = read_screen()
                if not refreshed or sign_in_action(refreshed, listing_marker) != action:
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
            if click(read_screen(), 'Next'):
                submitted.add(action)
            deadline = time.monotonic() + timeout
        elif action == 'start':
            if sign_in_attempts >= 3:
                raise RuntimeError('Google Play returned to Sign in after three attempts; device progress is retained')
            click(xml, 'Sign in')
            sign_in_attempts += 1
            # Play can drop back to its landing page while account setup starts.
            # A new attempt may legitimately show the credential screens again.
            submitted.clear()
            print(f'Opened Google Play sign-in (attempt {sign_in_attempts}/3); waiting for account setup.', flush=True)
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
            require_terminal()
            answer = input(('Complete the CAPTCHA yourself on the device, ' if action == 'captcha' else
                            'Complete the Google security check or unfamiliar screen on the device, ')
                           +
                           'then press Enter (/quit to pause): ')
            if answer.strip() == '/quit':
                raise RuntimeError('Google sign-in paused; the device is retained')
            deadline = time.monotonic() + timeout
        time.sleep(2)
    raise RuntimeError('Google sign-in did not finish; complete it on the device and resume')
