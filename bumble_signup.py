#!/usr/bin/env python3
"""Interactive Bumble onboarding using the recorded bumble-signup UI evidence."""
import argparse
import datetime as dt
import getpass
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from phone_setup_guard import verify_phone_setup

from setup_ui import adb_call, read_ui
from setup_network import ensure_network

PACKAGE = 'com.bumble.app'
ROOT = Path(__file__).resolve().parent


class UIActionError(RuntimeError):
    """A known UI failure whose message contains no credentials."""


def ask(label, default='', secret=False):
    prompt = f'{label}' + (f' [{default}]' if default else '') + ': '
    value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
    if value.lower() == '/quit':
        raise KeyboardInterrupt
    return value or default


def choose(label, options):
    print(label)
    for i, option in enumerate(options, 1):
        print(f'  {i}. {option}')
    while True:
        value = ask('Choose a number')
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]


def random_photos(directory=None):
    directory = Path(directory) if directory is not None else ROOT / 'bumble-signup' / 'photos'
    images = sorted(p for p in directory.iterdir() if p.is_file() and
                    p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.heic'))
    if len(images) < 4:
        raise RuntimeError('The Bumble photo pool needs at least four images')
    return secrets.SystemRandom().sample(images, 4)


def prompt_pool():
    entries = json.loads((ROOT / 'bumble-signup/prompt-pool.json').read_text())
    catalog = json.loads((ROOT / 'bumble-signup/prompt-picker/catalog.json').read_text())
    mapped = {(e['category'], e['question']) for e in catalog}
    grouped = {}
    for entry in entries:
        key = (entry.get('category'), entry.get('question'))
        answer = entry.get('answer', '')
        if key not in mapped or not 1 <= len(answer) <= 160 or not answer.isascii():
            raise RuntimeError('Bumble prompt pool contains an invalid mapped answer')
        grouped.setdefault(key, set()).add(answer)
    if set(grouped) != mapped or any(len(answers) != 3 for answers in grouped.values()) or len(entries) != 3 * len(mapped):
        raise RuntimeError('Each mapped Bumble prompt needs three distinct answers')
    return entries


def random_prompts(count=2, exclude=()):
    available = [e for e in prompt_pool() if e['question'] not in exclude]
    selected = []
    for _ in range(count):
        if not available:
            raise RuntimeError('Not enough distinct Bumble prompt questions')
        entry = secrets.choice(available)
        selected.append(dict(entry))
        available = [e for e in available if e['question'] != entry['question']]
    return selected


def profile_defaults():
    values = json.loads((ROOT / 'bumble-signup/profile-defaults.json').read_text())
    return values


def random_adult_birthday(today=None):
    """Return a valid random birthday for an adult aged 21 through 35."""
    today = today or dt.date.today()
    age = secrets.choice(range(21, 36))
    year = today.year - age
    month = secrets.choice(range(1, 13))
    while True:
        day = secrets.choice(range(1, 32))
        try:
            birthday = dt.date(year, month, day)
            break
        except ValueError:
            continue
    if (today.month, today.day) < (birthday.month, birthday.day):
        birthday = birthday.replace(year=year - 1)
    return birthday


def collect_profile(name='', gender=''):
    print('\nBumble signup — enter /quit at any prompt to stop. Phone and SMS inputs stay in memory.')
    while not name:
        name = ask('Profile first name')
    if not gender:
        gender = choose('Profile gender', ['Woman', 'Man', 'Nonbinary'])
    photos = random_photos()
    print('Randomly selected four supplied photos (video excluded):')
    for photo in photos:
        print('  ' + photo.name)
    print('Phone number, SMS code and other details will be requested at their Bumble screens.')
    print('Five random interests and two random written prompts will be added.')
    print('Height, habits, family plans and beliefs will use random visible choices.')
    defaults = profile_defaults()
    print('Using fixed operational choices only; profile details randomize at their screens.')
    return dict(defaults, name=name, gender=gender, photos=photos, prompts=random_prompts())


def ask_birthday():
    while True:
        try:
            birthday = dt.date.fromisoformat(ask('Birthday YYYY-MM-DD'))
            today = dt.date.today()
            age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
            if 18 <= age <= 120:
                return birthday
        except ValueError:
            pass
        print('Enter a valid birthday for an adult (18+).')


class Screen:
    def __init__(self, xml):
        self.tree = ET.fromstring(xml)
        self.nodes = list(self.tree.iter('node'))

    def find(self, label=None, rid=None):
        matches = []
        for node in self.nodes:
            if node.get('enabled') != 'true':
                continue
            if rid and not node.get('resource-id', '').endswith(':id/' + rid):
                continue
            if label and label not in (node.get('text'), node.get('content-desc')):
                continue
            if label or rid:
                matches.append(node)
        # Compose sometimes exposes both a navigation title and a footer with
        # the same text (e.g. Get verified). Prefer an actionable node, then the
        # lower control when neither advertises clickability.
        return max(matches, key=lambda n: (n.get('clickable') == 'true',
                   n.get('content-desc') == label if label else False,
                   center(n)[1]), default=None)

    def has(self, text):
        return any(text in (n.get('text', '') + '\n' + n.get('content-desc', '')) for n in self.nodes)

    def edits(self):
        return [n for n in self.nodes if n.get('class') == 'android.widget.EditText']

    def checked(self, label):
        node = self.find(label)
        parents = {child: parent for parent in self.tree.iter() for child in parent}
        while node is not None:
            if node.get('checked') == 'true' or node.get('selected') == 'true':
                return True
            node = parents.get(node)
        return False

    def interest_labels(self):
        labels = []
        for node in self.nodes:
            if node.get('checkable') != 'true' or node.get('class') == 'android.widget.Switch':
                continue
            words = [n.get('text', '') for n in node.iter('node')
                     if any(c.isalpha() for c in n.get('text', ''))]
            if words:
                label = max(words, key=len)
                if label not in labels:
                    labels.append(label)
        return labels


def center(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
    if not match:
        raise RuntimeError('UI target has no usable bounds')
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom <= top:
        raise RuntimeError('UI target is outside the visible screen')
    return (left + right) // 2, (top + bottom) // 2


class Signup:
    def __init__(self, serial, avd, output, profile):
        self.serial, self.avd, self.output, self.profile = serial, avd, output, profile
        self.last_state = None
        self.acted = set()
        self.staged = False
        self.staged_paths = set()
        self.restarted = False
        self.picker_selected = False
        self.started = time.monotonic()
        self.pending_sms_code = None
        self.sms_code_entered = False
        self.sms_arrow = None
        self.sms_retry_at = 0
        self.prompt_slot = 0
        self.active_prompt = None

    def call(self, *args):
        return adb_call(self.serial, *args)

    def read(self):
        return Screen(read_ui(self.serial))

    def tap(self, node):
        if node is None:
            raise UIActionError('Expected UI control is missing or disabled')
        x, y = center(node)
        self.call('shell', 'input', 'tap', str(x), str(y))

    def click(self, label=None, rid=None):
        if label in ('Continue', 'Upload'):
            # Compose can report footer bounds behind the IME. A tap there may
            # only dismiss the keyboard, leaving the form unchanged.
            keyboard = self.call('shell', 'dumpsys', 'input_method')
            if re.search(r'\bmInputShown=true\b', keyboard):
                self.call('shell', 'input', 'keyevent', 'KEYCODE_BACK')
        # Always refresh after a prior action: keyboard/Compose layouts can move.
        # Compose may briefly remove a footer while the IME is closing, so use a
        # short bounded retry instead of treating that transition as a missing control.
        node = None
        for attempt in range(5):
            node = self.read().find(label, rid)
            if node is not None:
                break
            if attempt < 4:
                time.sleep(0.4)
        self.tap(node)

    def type_text(self, value):
        # Type one character at a time with small natural timing variations.
        # Values travel through adb shell stdin, not host process arguments.
        if not value.isascii() or '%s' in value or '\n' in value:
            raise RuntimeError('This text needs manual keyboard entry in the emulator')
        rng = secrets.SystemRandom()
        for index, character in enumerate(value):
            token = '%s' if character == ' ' else character
            subprocess.run(['adb', '-s', self.serial, 'shell'],
                           input='input text ' + shlex.quote(token) + '\n',
                           capture_output=True, text=True, timeout=12, check=True)
            if index + 1 < len(value):
                delay = rng.uniform(0.045, 0.145)
                if rng.random() < 0.08:
                    delay += rng.uniform(0.18, 0.42)
                time.sleep(delay)

    def fill(self, index, value):
        node = self.read().edits()[index]
        self.tap(node)
        self.call('shell', 'input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
        self.call('shell', 'input', 'keyevent', 'KEYCODE_DEL')
        self.type_text(value)
        if self.read().edits()[index].get('text') != value:
            raise RuntimeError('Entered field did not match the supplied value')

    def progress(self, state):
        if state != self.last_state:
            print(f'Bumble: {state}', flush=True)
            self.last_state = state

    def manual(self, reason):
        print(f'Bumble needs your help: {reason}.\nUse the emulator, then return here.')
        self.capture_window()
        ask('Press Enter to inspect the screen again, or /quit to stop')
        self.acted.clear()

    def capture_window(self):
        # FLAG_SECURE can black out Android captures. Always use the existing
        # macOS window-only helper; never adb screencap or a full desktop capture.
        destination = self.output / 'screenshots' / (uuid.uuid4().hex + '.png')
        try:
            result = subprocess.run(['bash', str(ROOT / 'capture_emulator_window.sh'),
                                     self.avd, str(destination)], capture_output=True,
                                    text=True, timeout=30)
            if result.returncode == 0 and destination.is_file():
                print(f'Emulator window screenshot (may contain account details): {destination}')
                return destination
        except (OSError, subprocess.SubprocessError):
            pass
        print('Window screenshot unavailable; show the emulator window and enable macOS Screen Recording access.')
        return None

    def stage_photos(self):
        if self.staged:
            return
        folder = '/sdcard/Pictures/Signup-' + uuid.uuid4().hex[:12]
        self.call('shell', 'mkdir', '-p', folder)
        for i, path in enumerate(self.profile['photos'], 1):
            destination = f'{folder}/{i:02d}{path.suffix.lower()}'
            self.call('push', str(path), destination)
            self.staged_paths.add(destination.replace('/sdcard/', '/storage/emulated/0/'))
            self.call('shell', 'am', 'broadcast', '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE',
                      '-d', 'file://' + destination)
        self.staged = True

    def launch(self):
        self.call('shell', 'monkey', '-p', PACKAGE, '-c', 'android.intent.category.LAUNCHER', '1')

    def step(self, s):
        p = self.profile
        if s.has('Account blocked') and s.has('Community Guidelines'):
            return 'account blocked', 'account_blocked'
        if s.has('Protecting your account') and s.has('Please solve this puzzle'):
            return 'manual CAPTCHA', lambda: self.manual('Complete the CAPTCHA yourself on the device, then resume')
        if s.has('Please reload the challenge to try again'):
            return 'challenge loading error', lambda: self.manual('Challenge images failed to load; inspect the connection and retry manually')
        if s.has('using Bumble offline'):
            return 'offline connection', lambda: ensure_network(self.serial)
        if s.has('Loading') or not any(n.get('text') or n.get('content-desc') for n in s.nodes):
            return 'loading', None
        if s.has('Open camera') and s.has('Get ready to take a selfie'):
            return 'selfie instructions', 'verification_ready'
        if s.has('We need to verify your number'):
            return 'confirm phone number', lambda: self.click('OK')
        if s.has('Verify your number'):
            return 'SMS code', self.sms
        if s.has('Can we get your number'):
            return 'phone number', self.phone
        if s.find(rid='navbar_search') is not None:
            return 'country selection', self.country
        if s.has('Create an account'):
            return 'welcome', lambda: self.click('Create an account')
        if s.has('Do you want to create a passkey?'):
            return 'optional passkey', lambda: self.click('Not Now')
        if s.has('Now, can we get your location?'):
            return 'location', lambda: self.click('Set location services')
        if s.has('Don’t miss a beat, or a match'):
            return 'notifications', lambda: self.click('Allow notifications')
        if s.find(rid='permission_allow_foreground_only_button') is not None:
            return 'location permission', self.allow_location
        if s.find(rid='permission_allow_button') is not None and s.has('notifications'):
            return 'notification permission', lambda: self.click(rid='permission_allow_button')
        if s.has('Your birthday'):
            return 'name and birthday', self.intro
        if s.has('Make sure this is your correct age'):
            return 'confirm age', lambda: self.click('Confirm')
        if s.has('Which gender best describes you?'):
            return 'gender', lambda: self.select_continue(p['gender'])
        if s.has('Want to show your gender on your profile?'):
            return 'gender visibility', self.gender_visibility
        if s.has('Can we get your email?'):
            return 'recovery email', self.email
        if s.has('Want to keep up to date with all things Bumble?'):
            return 'marketing', lambda: self.click('MAYBE LATER')
        if s.has('Who would you like to meet?'):
            return 'dating preference', self.dating_preference
        if s.has('And what are you hoping to find?'):
            return 'dating intention', self.dating_intention
        if s.has('Choose 5 things') or s.has('Choose up to 5 interests for your profile'):
            return 'random interests', self.interests
        if s.has('Which one of your interests is your favorite?'):
            return 'favorite interest', self.favorite_interest
        if s.has('What’s your ethnicity?'):
            return 'random ethnicity', self.random_ethnicity
        for title in ['Your height', 'Let’s talk about your lifestyle',
                      'Do you have kids or family plans?', 'What’s important in your life?']:
            if s.has(title):
                return title, lambda title=title: self.random_profile_details(title)
        if s.has('Add at least one prompt'):
            # Recognize prompts saved by earlier runs, but only choose new
            # questions from the current device's mapped catalog.
            legacy = json.loads((ROOT / 'bumble-signup/prompt-pool-legacy.json').read_text())
            saved = {e['question'] for e in prompt_pool() + legacy if s.find(e['question']) is not None}
            if len(saved) >= 2:
                return 'two prompts saved', lambda: self.click('Continue')
            self.prompt_slot = len(saved)
            if 'prompts' not in self.profile:
                self.profile['prompts'] = random_prompts(exclude=saved)
            remaining = [e for e in self.profile['prompts'] if e['question'] not in saved]
            self.active_prompt = remaining[0] if remaining else random_prompts(1, exclude=saved)[0]
            return f'profile prompt {self.prompt_slot + 1}', lambda: self.click(
                'First prompt' if self.prompt_slot == 0 else 'Second prompt')
        if s.has('Pick a prompt'):
            return f'choose prompt {self.prompt_slot + 1}', self.choose_prompt
        if s.has('Your answer'):
            return f'prompt answer {self.prompt_slot + 1}', self.prompt_answer
        if s.has('Time to put a face to the name'):
            count = sum(n.get('content-desc', '').startswith('Delete ') for n in s.nodes)
            if count >= 4:
                return 'photos uploaded', lambda: self.click('Continue')
            return 'profile photos', self.photos
        if s.has('Upload photo from device'):
            return 'photo source', lambda: self.click('Upload photo from device')
        if s.find(rid='privacy_text') is not None:
            return 'photo picker', self.photo_picker
        if s.has('Crop photo'):
            return 'photo crop', lambda: self.click('Upload')
        if s.has('It’s cool to be kind'):
            return 'community guidelines', lambda: self.click('I accept')
        if s.has('There’s been a little glitch'):
            if self.restarted and s.find('Profile') is not None:
                return 'profile tab after feed error', lambda: self.click('Profile')
            return 'app restart', self.restart
        if s.has('New matches last 72 hours'):
            return 'match notice', lambda: self.click('Got it')
        if s.has('Add your ethnicity, if you’d like'):
            return 'optional ethnicity', lambda: self.click('Skip for now')
        if s.has('Start connecting'):
            if not p['verification']:
                return 'signup complete', 'signup_complete'
            return 'open profile navigation', lambda: self.click('Close')
        if s.has('How would you like to get verified?'):
            return 'verification menu', lambda: self.click('Get photo verified')
        if s.has('Get verified with a photo only'):
            return 'photo verification', lambda: self.click('Start')
        if s.has('Get verified with a selfie'):
            return 'selfie introduction', lambda: self.click('Get verified')
        if ((s.has('Photos and videos') and s.has('Profile strength')) or
                (s.find(rid='profile_editor_modeIcon') is not None and
                 s.find(rid='profile_editor_header_title') is not None)):
            return 'profile editor', self.open_verification
        if s.find(rid='menuNavigation_completeProfileCta') is not None:
            return 'profile', lambda: self.click(rid='menuNavigation_completeProfileCta')
        if s.has('Complete Profile'):
            return 'profile', lambda: self.click('Complete Profile')
        if s.find('Profile') is not None and s.find('People') is not None:
            if not p['verification']:
                return 'signup complete', 'signup_complete'
            return 'profile tab', lambda: self.click('Profile')
        return 'unrecognized screen', None

    def phone(self):
        self.phone_details()
        self.fill(0, self.profile['phone'])
        self.click('Continue')

    def allow_location(self):
        s = self.read()
        precise = s.find(rid='permission_location_accuracy_radio_fine')
        if precise is not None and precise.get('checked') != 'true':
            self.tap(precise)
        self.click(rid='permission_allow_foreground_only_button')

    def verify_permissions(self):
        dump = self.call('shell', 'dumpsys', 'package', PACKAGE)
        required = ['ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION', 'POST_NOTIFICATIONS']
        missing = [permission for permission in required if not re.search(
            r'android\.permission\.' + permission + r':\s+granted=true\b', dump)]
        if missing:
            raise UIActionError('Enable Bumble location and notifications in Android settings, then resume')
        print('Bumble: precise location and notification permissions verified.', flush=True)

    def phone_details(self):
        # Called only from phone entry/country selection after the app is open.
        while 'phone' not in self.profile:
            number = re.sub(r'[ ()-]', '', ask('National phone number (without country code)', secret=True))
            if re.fullmatch(r'\d{5,15}', number):
                self.profile['phone'] = number
            else:
                print('Enter 5–15 digits, without the country code.')

    def country(self):
        self.phone_details()
        country = self.profile.get('country', 'United States')
        self.fill(0, country)
        time.sleep(1)
        s = self.read()
        matches = [n for n in s.nodes if n.get('content-desc', '').startswith(country + ' country code ')]
        if len(matches) != 1:
            raise RuntimeError('Country selector did not return one matching country')
        self.tap(matches[0])
        self.fill(0, self.profile['phone'])
        self.click('Continue')

    def sms(self):
        if self.sms_code_entered:
            self.submit_sms()
            return
        s = self.read()
        # Keep Android coordinates, never coordinates from the Mac window.
        # Disabled footers still expose their position before the PIN is filled.
        arrow = next((n for n in s.nodes if n.get('resource-id', '').endswith(':id/reg_footer_button')
                      and n.get('content-desc') == 'Continue'), None)
        if s.has('Verify your number') and arrow is not None:
            self.sms_arrow = center(arrow)
        # A previous attempt or manual entry may already have filled the PIN.
        # Bumble exposes no digit text in its current hierarchy, but enables
        # this footer only when the code is ready to submit.
        submit = s.find(rid='reg_footer_button')
        if (s.has('Verify your number') and submit is not None and
                submit.get('content-desc') == 'Continue' and submit.get('clickable') == 'true'):
            self.pending_sms_code = None
            self.sms_code_entered = True
            self.sms_retry_at = time.monotonic() + 10
            self.tap(submit)
            return
        digit = s.find(rid='pinItem_textView')
        container = s.find(rid='verification_pinCodeInput')
        if digit is None and container is None:
            raise UIActionError('SMS input was not found; enter the code in the emulator')
        code = self.pending_sms_code or ask('Six-digit SMS code (Enter: paste device clipboard; /mac: Mac clipboard)', secret=True)
        if code.lower() == '/mac':
            try:
                code = subprocess.run(['pbpaste'], capture_output=True, text=True,
                                      check=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                raise UIActionError('Mac clipboard is unavailable; paste the code into the terminal') from None
        if code and not re.fullmatch(r'\d{6}', code):
            raise UIActionError('SMS code must have six digits')
        self.pending_sms_code = code or None
        if digit is not None:
            self.tap(digit)
        else:
            # Current Bumble exposes only the six-digit container, with no
            # child digit nodes. Focus its first slot using its live bounds.
            x, y = center(container)
            left = int(re.match(r'\[(\d+),', container.get('bounds')).group(1))
            self.call('shell', 'input', 'tap', str(left + (x - left) // 6), str(y))
        if code:
            self.type_text(code)
        else:
            self.call('shell', 'input', 'keyevent', 'KEYCODE_PASTE')
        # The code has been delivered to Android; never automatically re-enter it.
        self.pending_sms_code = None
        self.sms_code_entered = True
        self.submit_sms()

    def submit_sms(self):
        self.sms_retry_at = time.monotonic() + 10
        # Some releases submit automatically; click only if still at code entry.
        for attempt in range(4):
            try:
                s = self.read()
            except (RuntimeError, ET.ParseError, subprocess.SubprocessError):
                # UIAutomator can fail after the PIN is visibly filled.
                # Retain the footer observed on this same SMS screen.
                break
            if not s.has('Verify your number'):
                self.sms_code_entered = False
                return
            arrow = next((n for n in s.nodes if n.get('resource-id', '').endswith(':id/reg_footer_button')
                          and n.get('content-desc') == 'Continue'), None)
            if arrow is not None:
                self.sms_arrow = center(arrow)
            submit = s.find('Continue')
            if submit is not None:
                self.tap(submit)
                return
            if attempt < 3:
                time.sleep(0.3)
        if self.sms_code_entered and self.sms_arrow is not None:
            print('Bumble: tapping the saved SMS Continue arrow position.', flush=True)
            self.call('shell', 'input', 'tap', *map(str, self.sms_arrow))
            return
        raise UIActionError('SMS Continue arrow has no saved position; tap it in the emulator')

    def intro(self):
        if 'birthday' not in self.profile:
            self.profile['birthday'] = random_adult_birthday()
            print(f"Bumble birthday: {self.profile['birthday'].isoformat()} (random adult)", flush=True)
        birthday = self.profile['birthday']
        for i, value in enumerate([self.profile['name'], f'{birthday.month:02}',
                                   f'{birthday.day:02}', str(birthday.year)]):
            self.fill(i, value)
        self.click('Continue')

    def select_continue(self, label):
        s = self.read()
        node = (s.find(rid='toggle_with_text_toggle')
                if label == 'I’m open to dating everyone' else s.find(label))
        if node is None:
            raise RuntimeError('Requested profile choice is not available')
        if node.get('checked') != 'true' and node.get('selected') != 'true':
            self.tap(node)
        self.click('Continue')

    def gender_visibility(self):
        if 'show_gender' not in self.profile:
            self.profile['show_gender'] = secrets.choice([True, False])
            print('Bumble show gender: ' + ('Yes' if self.profile['show_gender'] else 'No'), flush=True)
        s = self.read()
        toggle = s.find(rid='toggle_with_text_toggle')
        if toggle is None or toggle.get('checkable') != 'true':
            raise RuntimeError('Check the Show on profile toggle and continue manually')
        if (toggle.get('checked') == 'true') != self.profile['show_gender']:
            self.tap(toggle)
        self.click('Continue')

    def email(self):
        if 'email' not in self.profile:
            email = ask('Recovery email (Enter to skip)', secret=True)
            while email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                email = ask('Valid recovery email (Enter to skip)', secret=True)
            self.profile['email'] = email
        if self.profile['email']:
            self.fill(0, self.profile['email'])
            self.click('Continue')
        else:
            self.click('Skip')

    def dating_preference(self):
        if 'dating' not in self.profile:
            self.profile['dating'] = secrets.choice(
                ['I’m open to dating everyone', 'Men', 'Women', 'Nonbinary people'])
            print(f"Bumble dating preference: {self.profile['dating']} (random).", flush=True)
        self.select_continue(self.profile['dating'])

    def dating_intention(self):
        if 'intention' not in self.profile:
            self.profile['intention'] = secrets.choice([
                'A long-term relationship', 'A life partner', 'Open to seeing where things go',
                'Something casual', 'Marriage', 'Ethical non-monogamy'])
            print(f"Bumble dating intention: {self.profile['intention']} (random).", flush=True)
        self.select_continue(self.profile['intention'])

    def prompt_answer(self):
        if self.active_prompt is None:
            self.active_prompt = (self.profile.get('prompts') or random_prompts())[0]
        self.fill(0, self.active_prompt['answer'])
        self.click('Double tap to save your answer')

    def choose_prompt(self):
        if self.active_prompt is None:
            self.active_prompt = (self.profile.get('prompts') or random_prompts())[0]
        question = self.active_prompt['question']
        category = self.active_prompt.get('category')
        if category:
            seen = set()
            for forward in (False, True):
                for _ in range(10):
                    s = self.read()
                    if not s.has('Pick a prompt'):
                        raise UIActionError('Prompt picker is no longer open')
                    node = s.find(category)
                    if node is not None:
                        self.tap(node)
                        break
                    labels = tuple(n.get('text') for n in s.nodes if n.get('text') and 200 < center(n)[1] < 325)
                    marker = (forward, labels)
                    if marker in seen:
                        break
                    seen.add(marker)
                    self.swipe_prompt_picker(s, horizontal=True, forward=forward)
                else:
                    continue
                if node is not None:
                    break
            else:
                raise UIActionError('Mapped prompt category is unavailable; prompt catalog needs refreshing')
        # Categories may remember their scroll position from a previous visit.
        for _ in range(3):
            self.swipe_prompt_picker(self.read(), forward=False)
        seen = set()
        for _ in range(12):
            s = self.read()
            if not s.has('Pick a prompt'):
                raise UIActionError('Prompt picker is no longer open')
            node = s.find(question)
            if node is not None:
                self.tap(node)
                return
            labels = tuple(n.get('text') for n in s.nodes if n.get('text') and center(n)[1] > 340)
            if labels in seen:
                break
            seen.add(labels)
            self.swipe_prompt_picker(s)
        raise UIActionError('Chosen prompt is not visible; select it manually or return to the prompt list')

    def swipe_prompt_picker(self, s, horizontal=False, forward=True):
        if not s.has('Pick a prompt'):
            raise UIActionError('Refusing to scroll outside the prompt picker')
        bounds = lambda n: list(map(int, re.findall(r'\d+', n.get('bounds', ''))))
        if horizontal:
            strip = next((n for n in s.nodes if n.get('scrollable') == 'true' and
                          len(bounds(n)) == 4 and bounds(n)[2] - bounds(n)[0] > 3 * (bounds(n)[3] - bounds(n)[1])), None)
            if strip is None:
                raise UIActionError('Prompt category strip is unavailable')
            left, top, right, bottom = bounds(strip)
            start, end = (right - 100, (top + bottom) // 2), (left + 100, (top + bottom) // 2)
        else:
            left, top, right, bottom = bounds(s.nodes[0])
            x = (left + right) // 2
            start, end = (x, bottom - 400), (x, top + 600)
        if not forward:
            start, end = end, start
        self.call('shell', 'input', 'swipe', *map(str, (*start, *end)), '350')
        time.sleep(0.3)

    def interests(self):
        s = self.read()
        labels = s.interest_labels()
        existing = [label for label in labels if s.checked(label)]
        if 'interests' not in self.profile:
            available = [label for label in labels if s.find(label) is not None and label not in existing]
            if len(existing) > 5 or len(available) < 5 - len(existing):
                raise UIActionError('Not enough visible interests; finish the selection on screen')
            self.profile['interests'] = existing + secrets.SystemRandom().sample(available, 5 - len(existing))
        for label in self.profile['interests']:
            if not self.read().checked(label):
                self.click(label)
        verified = self.read()
        if not (verified.has('5/5 selected') or
                sum(verified.checked(label) for label in self.profile['interests']) == 5):
            raise UIActionError('Five interests were not confirmed; finish the selection on screen')
        print('Bumble interests: ' + ', '.join(self.profile['interests']))
        self.click('Continue')

    def random_profile_details(self, title):
        """Choose visible onboarding details instead of silently skipping them."""
        if title == 'Your height':
            choices = [n.get('text', '') for n in self.read().nodes
                       if re.fullmatch(r"(?:\d{3} cm|\d' \d{1,2}'')", n.get('text', ''))]
            groups = [choices]
        elif title == 'Let’s talk about your lifestyle':
            groups = [
                ['Yes, I drink', 'I drink sometimes', 'I rarely drink',
                 'No, I don’t drink', 'I’m sober'],
                ['I smoke sometimes', 'No, I don’t smoke',
                 'Yes, I smoke', 'I’m trying to quit'],
            ]
        elif title == 'Do you have kids or family plans?':
            groups = [
                ['Have kids', 'Don’t have kids'],
                ['Don’t want kids', 'Open to kids', 'Want kids', 'Not sure'],
            ]
        elif title == 'What’s important in your life?':
            groups = [
                ['Agnostic', 'Atheist', 'Buddhist', 'Catholic', 'Christian',
                 'Hindu', 'Jain', 'Jewish', 'Mormon', 'Latter-day Saint',
                 'Muslim', 'Zoroastrian', 'Sikh', 'Spiritual', 'Other'],
                ['Apolitical', 'Moderate', 'Liberal', 'Conservative'],
            ]
        else:
            raise UIActionError(f'Unsupported profile detail screen: {title}')

        selected = []
        for group in groups:
            screen = self.read()
            visible = [label for label in group if screen.find(label) is not None]
            if not visible:
                raise UIActionError(f'No visible choices found for {title}')
            choice = secrets.choice(visible)
            self.click(choice)
            selected.append(choice)
        self.profile.setdefault('profile_details', {})[title] = selected
        print(f"Bumble {title}: {', '.join(selected)}", flush=True)
        self.click('Continue')

    def random_ethnicity(self):
        labels = [
            'African American', 'Black', 'Black African', 'Black American',
            'Black Caribbean', 'Central Asian', 'Chinese Caribbean', 'East Asian',
            'European', 'Hispanic', 'Jewish', 'Indo-Caribbean', 'Latina', 'Latino',
            'Latinx', 'Middle Eastern', 'Native American', 'Pacific Islander',
            'South Asian', 'Southeast Asian', 'White', 'Other',
        ]
        screen = self.read()
        visible = [label for label in labels if screen.find(label) is not None]
        if not visible:
            raise UIActionError('No visible ethnicity choices found')
        choice = secrets.choice(visible)
        self.click(choice)
        show = secrets.choice([True, False])
        screen = self.read()
        toggle = screen.find(rid='ethnicity_selection_show_profile_toggle')
        if toggle is None or toggle.get('checkable') != 'true':
            raise UIActionError('Ethnicity visibility toggle is unavailable')
        if (toggle.get('checked') == 'true') != show:
            self.tap(toggle)
        self.profile['ethnicity'] = choice
        self.profile['show_ethnicity'] = show
        print(f"Bumble ethnicity: {choice}; show on profile: {'Yes' if show else 'No'}", flush=True)
        self.click('Continue')

    def favorite_interest(self):
        s = self.read()
        choices = [label for label in self.profile.get('interests', []) if s.find(label) is not None]
        if not choices:
            self.click('Skip')
            return
        favorite = self.profile.get('favorite_interest') or secrets.choice(choices)
        self.profile['favorite_interest'] = favorite
        self.click(favorite)
        self.click('Save')

    def photos(self):
        self.stage_photos()
        self.click('Add photo 1')

    def photo_picker(self):
        s = self.read()
        thumbnails = [n for n in s.nodes if n.get('content-desc', '').startswith('Photo taken on')]
        # Never guess among an existing library; the fresh phone contains only
        # the supplied photos. Existing/resumed devices use manual selection.
        media = self.call('shell', 'content', 'query', '--uri', 'content://media/external/images/media',
                          '--projection', '_data')
        library = {p.replace('/sdcard/', '/storage/emulated/0/') for p in
                   re.findall(r'^Row: \d+ _data=(.+)$', media, re.MULTILINE)}
        if not self.staged_paths or library != self.staged_paths:
            raise RuntimeError('Select the supplied photos manually; the media library contains other or unindexed images')
        if len(thumbnails) != len(self.profile['photos']):
            raise RuntimeError('Select only your supplied photos in the picker and tap Add')
        if not self.picker_selected:
            for n in thumbnails:
                self.tap(n)
            self.picker_selected = True
        s = self.read()
        button = s.find(rid='button_add')
        if button is None or button.get('text') != f'Add ({len(thumbnails)})':
            raise RuntimeError('Photo picker selection count does not match supplied photos')
        self.tap(button)

    def restart(self):
        if self.restarted:
            raise RuntimeError('Bumble still reports a glitch after one restart')
        self.call('shell', 'am', 'force-stop', PACKAGE)
        self.launch()
        self.restarted = True

    def open_verification(self):
        for _ in range(5):
            s = self.read()
            # Current native editor exposes the row's status as a button while
            # omitting its visible Verification label from accessibility.
            target = s.find('Verification')
            if target is None:
                target = s.find('Not ID verified')
            if target is not None:
                self.tap(target)
                return
            # Scroll only the editor, never the People/swiping screen.
            scroll = next((n for n in s.nodes if n.get('scrollable') == 'true'), None)
            if scroll is None:
                break
            x, y = center(scroll)
            self.call('shell', 'input', 'swipe', str(x), str(y + 200), str(x), str(y - 300), '400')
        raise RuntimeError('Verification row is not visible in the profile editor')

    def run(self):
        if 'package:' not in self.call('shell', 'pm', 'path', PACKAGE):
            raise RuntimeError('Bumble is not installed on the selected device')
        if self.avd != self.call('emu', 'avd', 'name').splitlines()[0].strip():
            raise RuntimeError('Selected emulator does not match the requested AVD')
        ensure_network(self.serial)
        self.launch()
        deadline = time.monotonic() + 120
        unknown_since = None
        while True:
            try:
                s = self.read()
                state, action = self.step(s)
                self.progress(state)
                if state not in ('SMS code', 'loading'):
                    self.sms_code_entered = False
                    self.sms_arrow = None
                if state == 'SMS code' and self.sms_code_entered and time.monotonic() >= self.sms_retry_at:
                    self.acted.discard(state)
                if state == 'unrecognized screen':
                    if unknown_since is None:
                        unknown_since = time.monotonic()
                else:
                    unknown_since = None
                if isinstance(action, str):
                    self.verify_permissions()
                    return action
                if action is not None and state not in self.acted:
                    self.acted.add(state)
                    action()
                    deadline = time.monotonic() + 120
                elif (time.monotonic() >= deadline or
                      (unknown_since is not None and time.monotonic() - unknown_since >= 10)):
                    self.manual('Screen needs attention; automatic actions are paused')
                    deadline = time.monotonic() + 120
                    unknown_since = None
            except UIActionError as error:
                self.manual(str(error))
                deadline = time.monotonic() + 120
            except (RuntimeError, IndexError, ET.ParseError, subprocess.SubprocessError):
                # Exceptions may contain adb arguments with personal information.
                self.manual('The expected UI action could not be verified; finish this screen manually')
                deadline = time.monotonic() + 120
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--profile-name', default='', help='First name chosen during phone creation')
    parser.add_argument('--profile-gender', choices=['Woman', 'Man', 'Nonbinary'], default='')
    parser.add_argument('--output', type=Path, required=True, help='Directory for non-sensitive status')
    args = parser.parse_args()
    started = time.monotonic()
    status, exit_code = 'failed', 1
    try:
        if not sys.stdin.isatty():
            print('Bumble requires a terminal for credentials and the SMS code. Resume with the command in SETUP.md.')
            status = 'awaiting_terminal'
            return 2
        verify_phone_setup(args.serial, args.avd, PACKAGE)
        profile = collect_profile(args.profile_name, args.profile_gender)
        status = Signup(args.serial, args.avd, args.output, profile).run()
        if status == 'verification_ready':
            print('Bumble signup complete. Ready for your selfie; continue with Open camera in the emulator.')
            exit_code = 0
        elif status == 'signup_complete':
            print('Bumble signup complete. Stopped before Start connecting.')
            exit_code = 0
        elif status == 'account_blocked':
            print('Bumble blocked this account after verification; no retry or bypass was attempted.')
            exit_code = 3
        else:
            print(f'Bumble stopped with status: {status}.')
    except (KeyboardInterrupt, EOFError):
        status, exit_code = 'paused', 2
        print('\nBumble signup paused; the phone and app data are retained.')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print('Bumble signup could not finish. Check the emulator and resume the helper.')
    finally:
        args.output.mkdir(parents=True, exist_ok=True)
        elapsed = round(time.monotonic() - started, 1)
        (args.output / 'status.json').write_text(json.dumps(dict(status=status, elapsed_seconds=elapsed)) + '\n')
        print(f'Bumble step elapsed: {elapsed:.1f}s')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
