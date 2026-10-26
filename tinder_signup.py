#!/usr/bin/env python3
"""Observe or run the recorded Tinder onboarding path with guarded actions.

Unknown screens and human-verification challenges always remain manual.
No app launch, force-stop, device reboot, or Bumble interaction is performed.
"""
import argparse
from datetime import date
import getpass
import hashlib
import json
from pathlib import Path
import random
import re
import shlex
import subprocess
import time
from typing import Protocol
import xml.etree.ElementTree as ET

from setup_ui import adb_call, read_ui
from play_store_install import button_center
from phone_setup_guard import verify_phone_setup

PACKAGE = 'com.tinder'
INVALID_CODE = 'The code you entered is invalid — please try again.'
HOUSE_RULES = {'Welcome to Tinder.', 'Please follow these House Rules.',
               'Be yourself.', 'Make sure your photos, age, and bio are true to who you are.',
               'Stay safe.', "Don't be too quick to give out personal information. Date Safely",
               'Play it cool.', 'Respect others and treat them as you would like to be treated.',
               'Be proactive.', 'Always report bad behavior.', 'I agree'}
TERMS = ('By tapping ‘Continue’ you agree to our Terms. Learn how we process your data '
         'in our Privacy Policy and Cookies Policy.')
LABELS = {TERMS, 'Tinder logo', 'Allow Tinder to send you notifications?', 'Allow',
          'Don’t allow', "Don't allow", 'Continue with Google', 'Continue with Phone Number',
          'Continue with Line', 'Continue with Email', 'Trouble signing in?'}
LABELS.update(HOUSE_RULES)
LABELS.update({'What’s your first name?', 'This is how it’ll appear on your profile.\nCan’t change it later.'})
PROFILE_WELCOME = 'There’s a lot out there to discover. But let’s get your profile set up first.'
LABELS.update({PROFILE_WELCOME, 'Let’s go', 'Edit name'})
LABELS.update({'Your b-day?', 'Your profile shows your age, not your birth date.', '/'})
LABELS.update({'What’s your gender?', 'Woman', 'Man', 'Show my gender on my profile'})
DISTANCE_BODY = 'Use the slider to set the maximum distance you want your potential matches to be located.'
LABELS.update({'Your distance preference?', DISTANCE_BODY, 'Distance Preference', '50 Mi',
               'You can change preferences later in Settings'})
RELATIONSHIP_GOALS = {'Long-term partner', 'Long-term, open to short', 'Short-term, open to long',
                      'Short-term fun', 'New friends', 'Still figuring it out'}
GOALS_BODY = "All good if it changes. There's something for everyone."
LABELS.update(RELATIONSHIP_GOALS | {'What are you looking for?', GOALS_BODY})
LABELS.update({'Skip', 'If school’s your thing…', 'Enter school name',
              'This is how it’ll appear on your profile.'})
LIFESTYLE_QUESTIONS = {'How often do you drink?', 'How often do you smoke?',
                       'Do you workout?', 'Do you have any pets?'}
LIFESTYLE_OPTIONS = {
    'How often do you drink?': ('Not for me', 'Sober', 'Sober curious', 'On special occasions',
                                'Socially on weekends', 'Most Nights'),
    'How often do you smoke?': ('Social smoker', 'Smoker when drinking', 'Non-smoker', 'Smoker',
                                'Trying to quit'),
    'Do you workout?': ('Everyday', 'Often', 'Sometimes', 'Never'),
    'Do you have any pets?': ('Dog', 'Cat', 'Reptile', 'Amphibian', 'Bird', 'Fish',
                              "Don't have but love", 'Other', 'Turtle', 'Hamster', 'Rabbit',
                              'Pet-free', 'All the pets', 'Want a pet'),
}
LABELS.update(LIFESTYLE_QUESTIONS | {'Do their habits match yours? You go first.',
    'Not for me', 'Sober', 'Sober curious', 'On special occasions', 'Socially on weekends',
    'Most Nights', 'Social smoker', 'Smoker when drinking', 'Non-smoker', 'Smoker',
    'Trying to quit', 'Everyday', 'Often', 'Sometimes', 'Never', 'Dog', 'Cat', 'Reptile',
    'Amphibian', 'Bird', 'Fish', "Don't have but love", 'Other', 'Turtle', 'Hamster',
    'Rabbit', 'Pet-free', 'All the pets', 'Want a pet', 'Next 0/4'})
PERSONALITY_QUESTIONS = {'What is your communication style?', 'How do you receive love?',
                         'What is your education level?', 'What is your zodiac sign?'}
PERSONALITY_OPTIONS = {
    'What is your communication style?': ('Big time texter', 'Phone caller', 'Video chatter',
                                           'Bad texter', 'Better in person'),
    'How do you receive love?': ('Thoughtful gestures', 'Presents', 'Touch', 'Compliments',
                                 'Time together'),
    'What is your education level?': ('Bachelors', 'In College', 'High School', 'PhD',
                                      'In Grad School', 'Masters', 'Trade School'),
    'What is your zodiac sign?': ('Capricorn', 'Aquarius', 'Pisces', 'Aries', 'Taurus',
                                  'Gemini', 'Cancer', 'Leo', 'Virgo', 'Libra', 'Scorpio',
                                  'Sagittarius'),
}
LABELS.update(PERSONALITY_QUESTIONS | {'What else makes you–you?',
    'Don’t hold back. Authenticity attracts authenticity.', 'Big time texter', 'Phone caller',
    'Video chatter', 'Bad texter', 'Better in person', 'Thoughtful gestures', 'Presents',
    'Touch', 'Compliments', 'Time together', 'Bachelors', 'In College', 'High School',
    'PhD', 'In Grad School', 'Masters', 'Trade School', 'Capricorn', 'Aquarius', 'Pisces',
    'Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo', 'Libra', 'Scorpio', 'Sagittarius'})
INTERESTS_BODY = 'Add up to 10 interests to your profile to help you find people who share what you love.'
INTEREST_OPTIONS = {'90s Kid', 'Comic-con', 'Harry Potter', 'NBA', 'MLB', 'Manga', 'Marvel',
                    'Dungeons & Dragons', 'Foodie', 'Food tours', 'Soto', 'Maggi', 'Biryani',
                    'Papeda', 'Sambal', 'Sate', 'Gudeg', 'Ludo', 'Sega', 'E-Sports',
                    'PlayStation', 'Fortnite', 'Among Us', 'Atari', 'Xbox', 'League of Legends'}
LABELS.update({'What are you into?', INTERESTS_BODY, 'Creativity', 'Freelancing', 'Songket',
    'Sasirangan', 'Ikat', 'Jumputan', 'Batik', 'Lurik', 'Ulos', 'Show more', 'Fan favorites',
    '90s Kid', 'Comic-con', 'Harry Potter', 'NBA', 'MLB', 'Manga', 'Marvel', 'Dungeons & Dragons',
    'Food and drink', 'Foodie', 'Food tours', 'Soto', 'Maggi', 'Biryani', 'Papeda', 'Sambal',
    'Sate', 'Gudeg', 'Gaming', 'Ludo', 'Sega', 'E-Sports', 'PlayStation', 'Fortnite',
    'Among Us', 'Atari', 'Xbox', 'League of Legends', 'Next 0/10'})
PHOTOS_BODY = 'Upload 2 photos to start. Add 4 or more to make your profile stand out.'
LABELS.update({'Add your recent pics', PHOTOS_BODY, 'Add photo'})
MEDIA_PACKAGES = {'com.google.android.providers.media.module', 'com.android.providers.media.module'}
PICKER_PRIVACY = 'This app can only access the photos you select'
LABELS.update({PICKER_PRIVACY, 'Recent', 'Photos', 'Albums', 'Cancel', 'More options', 'View selected', 'Add (1)', 'Add (4)'})
LABELS.update({'Edit photos', 'Done', 'Back', 'Zoomable Image', 'Image', 'Remove', 'Replace'})
LABELS.update({'Profile photo, added', 'Delete photo'})
BIO_BODY = 'Write a bio and a prompt to help your profile stand out and spark conversations.'
LABELS.update({'Share more about yourself', BIO_BODY, 'About me',
    'Introduce yourself to make a strong impression.', 'Add bio', 'Select a prompt',
    'Answer a prompt to show off your personality.', 'Add prompt',
    'Adding a short intro about you could lead to 25% more matches'})
LOCATION_BODY = 'Set your location to see who’s in your neighborhood or beyond. You won’t be able to match with people otherwise.'
LABELS.update({'So, are you from around here?', LOCATION_BODY, 'How is my location used?'})
PERMISSION_PACKAGES = {'com.google.android.permissioncontroller', 'com.android.permissioncontroller'}
LOCATION_PERMISSION = 'Allow Tinder to access this device’s location?'
LABELS.update({LOCATION_PERMISSION, 'This app stated it may share location data with third parties',
              'Precise', 'Approximate', 'While using the app', 'Only this time'})
ACCURACY_MESSAGE = 'For a better experience, your device will need to use Location Accuracy '
LABELS.update({ACCURACY_MESSAGE, 'The following settings should be on:', 'Wi‑Fi scanning',
    'You can change this at any time in location settings. Manage settings or learn more',
    'No thanks', 'Turn on'})
LOCKED_MESSAGE = 'Your account has been temporarily locked due to suspicious activity. Your profile is hidden and not visible to other Tinder users. Here’s what’s next:'
LABELS.update({'We need to know it’s you', LOCKED_MESSAGE, 'Complete a video selfie to get back in',
    'Help us confirm you’re a real, live person and that your account meets Tinder’s Terms. If you don’t, your account will be closed.',
    'Show others you’re the real deal',
    'If you have eligible profile photos, you can get a Photo Verification badge for your profile.',
    'Get verified'})
LABELS.update({'Choose a phone number', 'Can we get your number?', 'Phone Number', 'US +1', 'Next',
               INVALID_CODE,
               'Enter your code', 'Resend', 'Didn’t get anything? No worries, let’s try again.',
               'Opt out anytime via account settings or reply “STOP.” Message frequency varies; data rates may apply.',
               'By entering your number and tapping “Next,” you agree to get account (e.g. verification codes, activity updates, profile alerts) and promotional texts from Tinder. Texts may be automated. Consent not required for purchase.'})
EMAIL_RECOVERY_BODY = "Don't lose access to your account, verify your email."
LABELS.update({'Your email?', 'Enter email', EMAIL_RECOVERY_BODY, 'Sign in with Google',
               'Verify instantly by connecting your Google account', 'Back button'})


class CredentialsProvider(Protocol):
    """An API provider can implement this interface without changing UI actions."""
    def phone_number(self) -> str: ...
    def verification_code(self) -> str: ...


class ManualCredentials:
    def phone_number(self):
        return getpass.getpass('Tinder phone number including country code (hidden; not saved): ').strip()

    def verification_code(self):
        return getpass.getpass('Tinder verification code (hidden; not saved): ').strip()


def continue_with_phone(serial):
    """Accept the displayed terms and choose the explicitly authorized phone flow."""
    xml = read_ui(serial)
    if classify(xml) != 'welcome-terms-and-login':
        raise RuntimeError('Expected observed Tinder welcome and terms screen')
    tap_label(serial, xml, 'Continue with Phone Number')


def dismiss_google_number_hint(serial):
    """Dismiss the Google SIM-number suggestion without choosing a number."""
    xml = read_ui(serial)
    if classify(xml) != 'google-number-hint':
        raise RuntimeError('Expected observed Google phone-number hint')
    adb_call(serial, 'shell', 'input', 'keyevent', 'KEYCODE_BACK')


def agree_house_rules(serial):
    """Explicit action only: caller must obtain the user's agreement first."""
    xml = read_ui(serial)
    if classify(xml) != 'house-rules':
        raise RuntimeError('Expected observed Tinder House Rules screen')
    point = button_center(xml, 'I agree')
    if not point:
        raise RuntimeError('House Rules agreement control missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print('Tapped explicitly authorized House Rules agreement.', flush=True)


def decline_optional_wifi_scanning(serial):
    xml = read_ui(serial)
    if classify(xml) != 'location-accuracy-prompt':
        raise RuntimeError('Expected observed Google Location Accuracy prompt')
    buttons = [n for n in ET.fromstring(xml).iter('node') if n.get('package') == 'com.google.android.gms'
               and n.get('resource-id') == 'android:id/button2' and n.get('text') == 'No thanks'
               and n.get('enabled') == 'true' and n.get('clickable') == 'true']
    if len(buttons) != 1:
        raise RuntimeError('Optional accuracy decline control missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', buttons[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Accuracy decline control bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def allow_foreground_location(serial):
    xml = read_ui(serial)
    if classify(xml) != 'location-permission':
        raise RuntimeError('Expected observed Tinder Android location permission')
    buttons = [n for n in ET.fromstring(xml).iter('node') if n.get('package') in PERMISSION_PACKAGES
               and n.get('resource-id') == 'com.android.permissioncontroller:id/permission_allow_foreground_only_button'
               and n.get('text') == 'While using the app' and n.get('enabled') == 'true' and n.get('clickable') == 'true']
    if len(buttons) != 1:
        raise RuntimeError('Foreground location control missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', buttons[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Location permission control bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))
    print('Granted authorized foreground location; precision unchanged; no background grant.', flush=True)


def allow_location_rationale(serial):
    xml = read_ui(serial)
    if classify(xml) != 'location-rationale':
        raise RuntimeError('Expected observed Tinder location explanation')
    tap_label(serial, xml, 'Allow')


def choose_notifications(serial, allow):
    """Apply only the exact Tinder Android notification permission choice."""
    xml = read_ui(serial)
    if classify(xml) != 'notification-permission':
        raise RuntimeError('Expected observed Tinder notification permission')
    resource = ('com.android.permissioncontroller:id/permission_allow_button' if allow else
                'com.android.permissioncontroller:id/permission_deny_button')
    controls = [node for node in ET.fromstring(xml).iter('node')
                if node.get('package') in PERMISSION_PACKAGES and
                node.get('resource-id') == resource and node.get('clickable') == 'true' and
                node.get('enabled') == 'true']
    if len(controls) != 1:
        raise RuntimeError('Notification permission control is missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', controls[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Notification permission control bounds are unavailable')
    left, top, right, bottom = map(int, match.groups())
    point = ((left + right) // 2, (top + bottom) // 2)
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print(('Allowed' if allow else 'Declined') + ' Tinder notifications.', flush=True)


def continue_photos(serial):
    """Explicit opt-in advance; never part of automatic photo upload handling."""
    xml = read_ui(serial)
    if classify(xml) != 'photos-manual-stop':
        raise RuntimeError('Expected observed Tinder photo page')
    count = sum(n.get('package') == PACKAGE and n.get('content-desc') == 'Profile photo, added'
                for n in ET.fromstring(xml).iter('node'))
    if count != 4:
        raise RuntimeError('Expected four added photos; no Next action taken')
    tap_resource(serial, xml, 'text_button')
    print('Tapped explicitly authorized photo-page Next; inspect next screen.', flush=True)


def finish_photo_edit(serial):
    xml = read_ui(serial)
    if classify(xml) != 'photo-editor':
        raise RuntimeError('Expected observed four-photo editor; no Done action taken')
    tap_label(serial, xml, 'Done')
    print('Finished authorized four-photo edit only; onboarding Next not tapped.', flush=True)


def open_photo_picker(serial):
    xml = read_ui(serial)
    if classify(xml) != 'photos-manual-stop':
        raise RuntimeError('Expected observed Tinder photos screen')
    slots = [n for n in ET.fromstring(xml).iter('node') if n.get('package') == PACKAGE and
             n.get('content-desc') == 'Add photo' and n.get('clickable') == 'true' and n.get('enabled') == 'true']
    if not 1 <= len(slots) <= 6:
        raise RuntimeError('No unambiguous empty photo slots available')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', slots[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Photo slot bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def verify_supplied_photo_library(serial, photos):
    """Only automate an exact library of explicitly supplied, hash-matched photos."""
    paths = [Path(p) for p in photos]
    if not paths or any(not p.is_file() for p in paths):
        raise RuntimeError('Supplied photo files unavailable')
    expected = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in paths)
    media = adb_call(serial, 'shell', 'content', 'query', '--uri', 'content://media/external/images/media', '--projection', '_data')
    library = re.findall(r'^Row: \d+ _data=(.+)$', media, re.MULTILINE)
    if len(library) != len(paths) or any(not p.startswith('/storage/emulated/0/') or '\n' in p for p in library):
        raise RuntimeError('Photo library is not an exact supplied set; select manually')
    actual = []
    for path in library:
        result = adb_call(serial, 'shell', 'sha256sum ' + shlex.quote(path))
        match = re.match(r'^([a-f0-9]{64})\s', result)
        if not match:
            raise RuntimeError('Device photo hash unavailable')
        actual.append(match.group(1))
    if sorted(actual) != expected:
        raise RuntimeError('Device photo hashes differ from supplied set; no selection made')
    return len(library)


def pick_supplied_photo(serial, photos, index=0):
    xml = read_ui(serial)
    if classify(xml) != 'android-photo-picker':
        raise RuntimeError('Expected observed Android photo picker')
    count = verify_supplied_photo_library(serial, photos)
    thumbnails = [n for n in ET.fromstring(xml).iter('node')
                  if n.get('package') in MEDIA_PACKAGES and n.get('content-desc', '').startswith('Photo taken on')
                  and n.get('clickable') == 'true' and n.get('enabled') == 'true']
    if len(thumbnails) != count or not 0 <= index < count:
        raise RuntimeError('Picker thumbnail count differs from verified library')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', thumbnails[index].get('bounds', ''))
    if not match:
        raise RuntimeError('Photo thumbnail bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def confirm_four_photos(serial, photos):
    xml = read_ui(serial)
    if classify(xml) != 'android-photo-picker' or verify_supplied_photo_library(serial, photos) != 4:
        raise RuntimeError('Expected picker and exact four supplied photos')
    nodes = [n for n in ET.fromstring(xml).iter('node') if n.get('package') in MEDIA_PACKAGES]
    orders = [n.get('text') for n in nodes if n.get('resource-id', '').endswith(':id/selected_order')]
    if sorted(orders) != ['1', '2', '3', '4']:
        raise RuntimeError('Exactly four selected photos required; no confirmation made')
    buttons = [n for n in nodes if n.get('resource-id', '').endswith(':id/button_add') and n.get('text') == 'Add (4)'
               and n.get('enabled') == 'true' and n.get('clickable') == 'true']
    if len(buttons) != 1:
        raise RuntimeError('Photo picker Add (4) control unavailable')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', buttons[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Photo picker confirmation bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def skip_optional(serial):
    xml = read_ui(serial)
    if classify(xml) not in {'school', 'lifestyle', 'personality', 'interests', 'bio-and-prompt'}:
        raise RuntimeError('Expected reviewed optional screen; no skip taken')
    tap_resource(serial, xml, 'onboarding_skip_button')


def _selection_progress(xml, maximum):
    pattern = re.compile(rf'Next (\d+)/{maximum}')
    values = [value for n in ET.fromstring(xml).iter('node') if n.get('package') == PACKAGE
              for value in (n.get('text', ''), n.get('content-desc', '')) if pattern.fullmatch(value)]
    if len(values) != 1:
        raise RuntimeError(f'Expected one observed Next count out of {maximum}')
    return int(pattern.fullmatch(values[0]).group(1))


def _visible_reviewed_options(xml, options):
    values = {value for n in ET.fromstring(xml).iter('node') if n.get('package') == PACKAGE
              for value in (n.get('text', ''), n.get('content-desc', ''))}
    return [option for option in options if option in values]


def select_random_single_choice_traits(serial, state, rng=None):
    """Choose one reviewed answer for each of four single-choice trait questions."""
    groups = LIFESTYLE_OPTIONS if state == 'lifestyle' else PERSONALITY_OPTIONS if state == 'personality' else None
    if groups is None:
        raise RuntimeError('Expected lifestyle or personality single-choice screen')
    rng = rng or random
    current = read_ui(serial)
    if classify(current) != state or _selection_progress(current, 4) != 0:
        raise RuntimeError('Expected an untouched observed single-choice trait screen')
    chosen = []
    for progress, options in enumerate(groups.values(), start=1):
        visible = _visible_reviewed_options(current, options)
        if len(visible) < 2:
            raise RuntimeError('Reviewed trait choices are missing or changed')
        choice = rng.choice(visible)
        tap_label(serial, current, choice)
        current = read_ui(serial)
        if classify(current) != state or _selection_progress(current, 4) != progress:
            raise RuntimeError('Trait selection count did not advance as expected; Next not tapped')
        chosen.append(choice)
    tap_resource(serial, current, 'text_button')
    print(f'Randomly selected one reviewed answer for each {state} question and tapped Next.', flush=True)
    return chosen


def select_random_interests(serial, rng=None):
    """Choose two or three distinct reviewed interests, then advance."""
    rng = rng or random
    current = read_ui(serial)
    if classify(current) != 'interests' or _selection_progress(current, 10) != 0:
        raise RuntimeError('Expected an untouched observed interests screen')
    visible = _visible_reviewed_options(current, INTEREST_OPTIONS)
    if len(visible) < 3:
        raise RuntimeError('Fewer than three reviewed interests are visible')
    chosen = rng.sample(visible, rng.randint(2, 3))
    for progress, choice in enumerate(chosen, start=1):
        tap_label(serial, current, choice)
        current = read_ui(serial)
        if classify(current) != 'interests' or _selection_progress(current, 10) != progress:
            raise RuntimeError('Interest selection count did not advance as expected; Next not tapped')
    tap_resource(serial, current, 'text_button')
    print(f'Randomly selected {len(chosen)} distinct reviewed interests and tapped Next.', flush=True)
    return chosen


def randomize_current_traits(serial):
    """Apply the bounded random policy to the current reviewed traits screen."""
    state = classify(read_ui(serial))
    if state in {'lifestyle', 'personality'}:
        return select_random_single_choice_traits(serial, state)
    if state == 'interests':
        return select_random_interests(serial)
    raise RuntimeError('Expected a reviewed lifestyle, personality, or interests screen')


def tap_label(serial, xml, label):
    """Tap one exact reviewed label's enabled clickable ancestor (Compose-safe)."""
    root = ET.fromstring(xml)
    parents = {child: parent for parent in root.iter() for child in parent}
    matches = [n for n in root.iter('node') if n.get('package') == PACKAGE and
               (n.get('text') == label or n.get('content-desc') == label)]
    if len(matches) != 1:
        raise RuntimeError('Label missing or ambiguous')
    node = matches[0]
    while node.get('clickable') != 'true':
        node = parents.get(node)
        if node is None or node.get('package') != PACKAGE:
            raise RuntimeError('Label has no app-owned clickable control')
    if node.get('enabled') != 'true':
        raise RuntimeError('Label control is disabled')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
    if not match:
        raise RuntimeError('Label control bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def select_relationship_goal(serial, goal):
    if goal not in RELATIONSHIP_GOALS:
        raise RuntimeError('Unobserved relationship goal')
    xml = read_ui(serial)
    if classify(xml) != 'relationship-goals':
        raise RuntimeError('Expected observed relationship goals screen')
    tap_label(serial, xml, goal)
    current = read_ui(serial)
    if classify(current) != 'relationship-goals':
        print('Screen changed after goal choice; inspect before further action.', flush=True)
        return
    tap_label(serial, current, 'Next')


def continue_default_distance(serial):
    xml = read_ui(serial)
    if classify(xml) != 'distance-preference':
        raise RuntimeError('Expected observed Tinder distance preference screen')
    if not any(n.get('package') == PACKAGE and n.get('text') == '50 Mi'
               for n in ET.fromstring(xml).iter('node')):
        raise RuntimeError('Distance differs from observed default; review manually')
    tap_resource(serial, xml, 'text_button')
    print('Kept observed 50-mile default distance and tapped Next.', flush=True)


def tap_resource(serial, xml, resource_id):
    nodes = [n for n in ET.fromstring(xml).iter('node')
             if n.get('package') == PACKAGE and n.get('resource-id') == PACKAGE + ':id/' + resource_id]
    if len(nodes) != 1 or nodes[0].get('enabled') != 'true' or nodes[0].get('clickable') != 'true':
        raise RuntimeError('Requested control missing, ambiguous, or unavailable')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', nodes[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Requested control bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))


def select_gender(serial, gender, show_on_profile):
    """Apply explicit user choices only; never randomize identity or visibility."""
    if gender not in ('Woman', 'Man') or not isinstance(show_on_profile, bool):
        raise RuntimeError('Explicit gender and visibility choices are required')
    xml = read_ui(serial)
    if classify(xml) != 'gender':
        raise RuntimeError('Expected observed Tinder gender screen')
    tap_resource(serial, xml, 'gender_female_selection_button' if gender == 'Woman' else 'gender_male_selection_button')
    current = read_ui(serial)
    if classify(current) != 'gender':
        print('Screen changed after gender choice; inspect before taking further action.', flush=True)
        return
    boxes = [n for n in ET.fromstring(current).iter('node')
             if n.get('resource-id') == PACKAGE + ':id/show_gender_on_profile_checkbox']
    if len(boxes) != 1 or boxes[0].get('checked') not in ('true', 'false'):
        raise RuntimeError('Gender visibility state unavailable')
    if (boxes[0].get('checked') == 'true') != show_on_profile:
        tap_resource(serial, current, 'show_gender_on_profile_checkbox')
        current = read_ui(serial)
    boxes = [n for n in ET.fromstring(current).iter('node')
             if n.get('resource-id') == PACKAGE + ':id/show_gender_on_profile_checkbox']
    if classify(current) != 'gender' or len(boxes) != 1 or boxes[0].get('checked') != str(show_on_profile).lower():
        raise RuntimeError('Gender visibility read-back did not match; Next not tapped')
    tap_resource(serial, current, 'text_button')
    print('Explicit gender and profile visibility choices applied; Next tapped.', flush=True)


def enter_birth_date(serial, iso_date):
    """Enter an explicitly supplied adult DOB on the observed MM/DD/YYYY screen."""
    birthday = date.fromisoformat(iso_date)
    today = date.today()
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    if age < 18 or age > 120:
        raise RuntimeError('An actual adult birth date is required')
    xml = read_ui(serial)
    if classify(xml) != 'birth-date':
        raise RuntimeError('Expected observed Tinder birth-date screen')
    fields = [n for n in ET.fromstring(xml).iter('node')
              if n.get('package') == PACKAGE and n.get('class') == 'android.widget.EditText']
    if ''.join(n.get('text', '') for n in fields) != 'MMDDYYYY':
        raise RuntimeError('Expected empty observed MM/DD/YYYY fields; review existing date manually')
    bounds = []
    for field in fields:
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', field.get('bounds', ''))
        if not match:
            raise RuntimeError('Birth-date field bounds unavailable')
        bounds.append(tuple(map(int, match.groups())))
    if any(bounds[i][0] >= bounds[i+1][0] for i in range(7)):
        raise RuntimeError('Birth-date field ordering differs from observed layout')
    for digit, (l, t, r, b) in zip(birthday.strftime('%m%d%Y'), bounds):
        # One field at a time; never depend on automatic focus movement.
        subprocess.run(['adb', '-s', serial, 'shell'],
                       input=f'input tap {(l+r)//2} {(t+b)//2}\ninput text {digit}\n',
                       text=True, capture_output=True, check=True, timeout=12)
    current = read_ui(serial)
    values = ''.join(n.get('text', '') for n in ET.fromstring(current).iter('node')
                     if n.get('package') == PACKAGE and n.get('class') == 'android.widget.EditText')
    if classify(current) != 'birth-date' or values != birthday.strftime('%m%d%Y'):
        raise RuntimeError('Birth-date read-back did not match; Next not tapped')
    point = button_center(current, 'Next')
    if not point:
        raise RuntimeError('Birth-date Next control missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print('User-supplied birth date verified and Next tapped; date not saved.', flush=True)


def start_profile(serial):
    xml = read_ui(serial)
    if classify(xml) != 'profile-welcome':
        raise RuntimeError('Expected observed Tinder profile welcome screen')
    point = button_center(xml, 'Let’s go')
    if not point:
        raise RuntimeError('Profile welcome continue control missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))


def enter_first_name(serial, name):
    """Fill a user-supplied first name and advance the observed name screen."""
    xml = read_ui(serial)
    if classify(xml) != 'first-name':
        raise RuntimeError('Expected observed Tinder first-name screen')
    # Android input text requires additional encoding for other characters.
    # Reject unsupported input rather than silently altering the user's name.
    if not re.fullmatch(r'[A-Za-z]{1,40}', name):
        raise RuntimeError('Enter this name manually; automated entry currently supports ASCII letters only')
    fields = [n for n in ET.fromstring(xml).iter('node')
              if n.get('package') == PACKAGE and
              n.get('resource-id') == PACKAGE + ':id/onboarding_name_edit_text']
    if len(fields) != 1:
        raise RuntimeError('First-name field missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', fields[0].get('bounds', ''))
    if not match:
        raise RuntimeError('First-name field bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))
    adb_call(serial, 'shell', 'input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
    adb_call(serial, 'shell', 'input', 'keyevent', 'KEYCODE_DEL')
    subprocess.run(['adb', '-s', serial, 'shell'], input='input text ' + shlex.quote(name) + '\n',
                   text=True, capture_output=True, check=True, timeout=12)
    current = read_ui(serial)
    values = [n.get('text', '') for n in ET.fromstring(current).iter('node')
              if n.get('resource-id') == PACKAGE + ':id/onboarding_name_edit_text']
    if classify(current) != 'first-name' or values != [name]:
        raise RuntimeError('First-name read-back did not match; Next not tapped')
    point = button_center(current, 'Next')
    if not point:
        raise RuntimeError('First-name Next control missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print('User-supplied first name verified and Next tapped; value not saved.', flush=True)


def enter_phone(serial, provider, submit=False):
    xml = read_ui(serial)
    if classify(xml) != 'phone-entry':
        raise RuntimeError('Expected observed Tinder phone-entry screen')
    nodes = list(ET.fromstring(xml).iter('node'))
    if not any(n.get('text') == 'US +1' for n in nodes):
        raise RuntimeError('Country selection is not the observed US +1; choose it manually')
    number = re.sub(r'[ ()-]', '', provider.phone_number())
    if not re.fullmatch(r'\+1\d{10}', number):
        raise RuntimeError('This observed screen requires a US +1 phone number')
    fields = [n for n in nodes if n.get('resource-id') == PACKAGE + ':id/phoneNumberInputView']
    if len(fields) != 1:
        raise RuntimeError('Phone field is missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', fields[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Phone field bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))
    adb_call(serial, 'shell', 'input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
    adb_call(serial, 'shell', 'input', 'keyevent', 'KEYCODE_DEL')
    # Keep phone/code values out of host process arguments and fixture files.
    subprocess.run(['adb', '-s', serial, 'shell'], input='input text ' + shlex.quote(number[2:]) + '\n',
                   text=True, capture_output=True, check=True, timeout=12)
    current_xml = read_ui(serial)
    current = ET.fromstring(current_xml)
    values = [n.get('text', '') for n in current.iter('node')
              if n.get('resource-id') == PACKAGE + ':id/phoneNumberInputView']
    if len(values) != 1 or re.sub(r'\D', '', values[0]) != number[2:]:
        raise RuntimeError('Phone field read-back did not match')
    if submit:
        if classify(current_xml) != 'phone-entry':
            raise RuntimeError('Phone-entry screen changed; SMS consent was not submitted')
        point = button_center(current_xml, 'Next')
        if not point:
            raise RuntimeError('Phone-entry Next control missing or ambiguous')
        adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
        print('Phone entered, verified, and submitted after explicit SMS-consent authorization.', flush=True)
    else:
        print('Phone entered and verified; Next has not been tapped. Review the displayed SMS consent.', flush=True)


def submit_existing_phone(serial):
    """Submit a privately prefilled US phone field after SMS consent."""
    xml = read_ui(serial)
    if classify(xml) != 'phone-entry':
        raise RuntimeError('Expected observed Tinder phone-entry screen')
    fields = [node for node in ET.fromstring(xml).iter('node')
              if node.get('package') == PACKAGE and
              node.get('resource-id') == 'com.tinder:id/phoneNumberInputView']
    if len(fields) != 1 or not re.fullmatch(r'\d{10}', fields[0].get('text', '')):
        raise RuntimeError('Phone field must contain exactly ten private US digits')
    point = button_center(xml, 'Next')
    if not point:
        raise RuntimeError('Phone Next control is missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print('Privately entered phone submitted after explicit SMS consent.', flush=True)


def enter_code(serial, provider):
    xml = read_ui(serial)
    if classify(xml) != 'verification-code':
        raise RuntimeError('Expected observed Tinder verification-code screen')
    code = provider.verification_code()
    if not re.fullmatch(r'\d{6}', code):
        raise RuntimeError('This observed screen requires six digits')
    tree = ET.fromstring(xml)
    first = next(n for n in tree.iter('node') if n.get('resource-id') == PACKAGE + ':id/otp_input_view_0')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', first.get('bounds', ''))
    if not match:
        raise RuntimeError('Code field bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))
    subprocess.run(['adb', '-s', serial, 'shell'], input='input text ' + shlex.quote(code) + '\n',
                   text=True, capture_output=True, check=True, timeout=12)
    current = read_ui(serial)
    if classify(current) == 'verification-code-invalid':
        print('Tinder rejected the code and cleared the fields; request a fresh code. No retry taken.', flush=True)
        return
    if classify(current) != 'verification-code':
        print('Screen changed after code entry; inspect the next screen.', flush=True)
        return
    values = {n.get('resource-id'): n.get('text', '') for n in ET.fromstring(current).iter('node')}
    if ''.join(values.get(PACKAGE + f':id/otp_input_view_{i}', '') for i in range(6)) != code:
        raise RuntimeError('Verification-code read-back did not match; no additional submission made (the app may auto-submit)')
    point = button_center(current, 'Next')
    if not point:
        raise RuntimeError('Verification Next control missing or ambiguous')
    adb_call(serial, 'shell', 'input', 'tap', *map(str, point))
    print('Verification code submitted; value not logged or saved.', flush=True)


def enter_email(serial, email):
    """Enter a user-supplied recovery email without selecting Google sign-in."""
    if (not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@'
                         r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                         r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+', email)
            or len(email) > 254):
        raise RuntimeError('Enter a valid email address manually')
    xml = read_ui(serial)
    if classify(xml) != 'email-recovery-manual-stop':
        raise RuntimeError('Expected observed Tinder recovery-email screen')
    fields = [n for n in ET.fromstring(xml).iter('node')
              if n.get('package') == PACKAGE and
              n.get('resource-id') == PACKAGE + ':id/collect_email_input_edit_text']
    if len(fields) != 1:
        raise RuntimeError('Recovery-email field missing or ambiguous')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', fields[0].get('bounds', ''))
    if not match:
        raise RuntimeError('Recovery-email field bounds unavailable')
    l, t, r, b = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((l+r)//2), str((t+b)//2))
    adb_call(serial, 'shell', 'input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
    adb_call(serial, 'shell', 'input', 'keyevent', 'KEYCODE_DEL')
    # Pass the private value over adb's stdin so it never appears in argv or fixtures.
    subprocess.run(['adb', '-s', serial, 'shell'], input='input text ' + shlex.quote(email) + '\n',
                   text=True, capture_output=True, check=True, timeout=12)
    current = read_ui(serial)
    values = [n.get('text', '') for n in ET.fromstring(current).iter('node')
              if n.get('resource-id') == PACKAGE + ':id/collect_email_input_edit_text']
    if classify(current) != 'email-recovery-manual-stop' or values != [email]:
        raise RuntimeError('Recovery-email read-back did not match; Next not tapped')
    # Accessibility still exposes Tinder's bottom button while the keyboard
    # physically covers it. Dismiss only the keyboard, then verify the private
    # value again before acting on the now-visible control.
    adb_call(serial, 'shell', 'input', 'keyevent', 'KEYCODE_BACK')
    current = read_ui(serial)
    values = [n.get('text', '') for n in ET.fromstring(current).iter('node')
              if n.get('resource-id') == PACKAGE + ':id/collect_email_input_edit_text']
    if classify(current) != 'email-recovery-manual-stop' or values != [email]:
        raise RuntimeError('Recovery email changed while dismissing keyboard; Next not tapped')
    buttons = [n for n in ET.fromstring(current).iter('node')
               if n.get('package') == PACKAGE and
               n.get('resource-id') == PACKAGE + ':id/text_button' and
               n.get('text') == 'Next']
    if len(buttons) != 1 or buttons[0].get('enabled') != 'true':
        raise RuntimeError('Recovery-email Next control is unavailable')
    tap_resource(serial, current, 'text_button')
    print('Recovery email verified and submitted; value not logged or saved.', flush=True)


def classify(xml):
    nodes = list(ET.fromstring(xml).iter('node'))
    tinder = {n.get('text', '') for n in nodes if n.get('package') == PACKAGE}
    if {'We need to know it’s you', LOCKED_MESSAGE, 'Complete a video selfie to get back in', 'Get verified'} <= tinder:
        return 'locked-video-selfie-manual-stop'
    visible = ' '.join(filter(None, (value for n in nodes if n.get('package') == PACKAGE
                                      for value in (n.get('text', ''), n.get('content-desc', ''))))).casefold()
    human_challenge_markers = ('captcha', 'recaptcha', "i'm not a robot", 'i am not a robot',
                               'prove you are human', "prove you're human", 'verify you are human',
                               "verify you're human", 'human verification', 'video selfie',
                               'face verification', 'photo verification')
    if any(marker in visible for marker in human_challenge_markers):
        return 'human-verification-manual-stop'
    permissions = {n.get('text', '') for n in nodes
                   if n.get('package') in ('com.google.android.permissioncontroller',
                                          'com.android.permissioncontroller')}
    google = {n.get('text', '') for n in nodes if n.get('package') == 'com.google.android.gms'}
    if {ACCURACY_MESSAGE, 'Wi‑Fi scanning', 'No thanks', 'Turn on'} <= google:
        return 'location-accuracy-prompt'
    if LOCATION_PERMISSION in permissions and 'While using the app' in permissions:
        return 'location-permission'
    descriptions = {n.get('content-desc', '') for n in nodes if n.get('package') == PACKAGE}
    if {'So, are you from around here?', LOCATION_BODY, 'Allow', 'How is my location used?'} <= tinder:
        return 'location-rationale'
    if {'Share more about yourself', BIO_BODY, 'About me', 'Select a prompt', 'Skip'} <= tinder:
        return 'bio-and-prompt'
    if {'Edit photos', 'Done'} <= tinder and 'Zoomable Image' in descriptions:
        images = sum(n.get('package') == PACKAGE and n.get('content-desc') == 'Image' for n in nodes)
        removes = sum(n.get('package') == PACKAGE and n.get('content-desc') == 'Remove' for n in nodes)
        if images == 4 and removes == 4:
            return 'photo-editor'
    media = [n for n in nodes if n.get('package') in MEDIA_PACKAGES]
    if any(n.get('text') == PICKER_PRIVACY for n in media) and any(
            n.get('content-desc', '').startswith('Photo taken on') for n in media):
        return 'android-photo-picker'
    if {'Add your recent pics', PHOTOS_BODY, 'Next'} <= tinder and 'Add photo' in descriptions:
        if any(n.get('resource-id') == PACKAGE + ':id/onboardingPhotoTitle' for n in nodes):
            return 'photos-manual-stop'
    if {'What are you into?', INTERESTS_BODY, 'Skip'} <= tinder:
        if any(n.get('resource-id') == PACKAGE + ':id/title_textview' for n in nodes):
            return 'interests'
    if PERSONALITY_QUESTIONS | {'What else makes you–you?', 'Skip'} <= tinder:
        return 'personality'
    if LIFESTYLE_QUESTIONS | {'Do their habits match yours? You go first.', 'Skip'} <= tinder:
        return 'lifestyle'
    if {'If school’s your thing…', 'Enter school name', 'Skip'} <= tinder:
        if any(n.get('resource-id') == PACKAGE + ':id/school_title' for n in nodes):
            return 'school'
    if {'What are you looking for?', GOALS_BODY, 'Next'} <= tinder and RELATIONSHIP_GOALS <= descriptions:
        return 'relationship-goals'
    if {'Your distance preference?', DISTANCE_BODY, 'Distance Preference', 'Next'} <= tinder:
        return 'distance-preference'
    if {'What’s your gender?', 'Woman', 'Man', 'Show my gender on my profile', 'Next'} <= tinder:
        required = {PACKAGE + ':id/' + value for value in
                    ('onboarding_binary_gender_title', 'gender_female_selection_button',
                     'gender_male_selection_button', 'show_gender_on_profile_checkbox')}
        if required <= {n.get('resource-id') for n in nodes if n.get('package') == PACKAGE}:
            return 'gender'
    if {'Your b-day?', 'Your profile shows your age, not your birth date.', 'Next'} <= tinder:
        if sum(n.get('package') == PACKAGE and n.get('class') == 'android.widget.EditText'
               for n in nodes) == 8:
            return 'birth-date'
    if {PROFILE_WELCOME, 'Let’s go', 'Edit name'} <= tinder:
        return 'profile-welcome'
    if ('What’s your first name?' in tinder and
            any(n.get('package') == PACKAGE and
                n.get('resource-id') == PACKAGE + ':id/onboarding_name_edit_text' for n in nodes)):
        return 'first-name'
    if {'Welcome to Tinder.', 'Please follow these House Rules.', 'I agree'} <= tinder:
        return 'house-rules'
    if ('Enter your code' in tinder and
            sum(n.get('resource-id', '').startswith(PACKAGE + ':id/otp_input_view_') for n in nodes) == 6):
        if INVALID_CODE in tinder:
            return 'verification-code-invalid'
        return 'verification-code'
    if 'Choose a phone number' in google:
        return 'google-number-hint'
    if ('Can we get your number?' in tinder and
            any(n.get('resource-id') == PACKAGE + ':id/phoneNumberInputView' for n in nodes)):
        return 'phone-entry'
    if ({'Your email?', EMAIL_RECOVERY_BODY, 'Sign in with Google'} <= tinder and
            any(n.get('package') == PACKAGE and
                n.get('resource-id') == PACKAGE + ':id/collect_email_input_edit_text'
                for n in nodes)):
        return 'email-recovery-manual-stop'
    if 'Allow Tinder to send you notifications?' in permissions:
        return 'notification-permission'
    if TERMS in tinder and 'Continue with Phone Number' in tinder:
        return 'welcome-terms-and-login'
    return 'unknown'


def sanitized_xml(xml):
    """Keep only reviewed static labels and structural fields in fixtures."""
    tree = ET.fromstring(xml)
    permitted = {'package', 'class', 'bounds', 'enabled', 'clickable', 'checkable',
                 'checked', 'selected', 'scrollable', 'password'}
    for node in tree.iter('node'):
        safe = {key: value for key, value in node.attrib.items() if key in permitted}
        rid = node.get('resource-id', '')
        if re.fullmatch(r'[a-zA-Z0-9_.]+:id/[a-zA-Z0-9_]+', rid):
            safe['resource-id'] = rid
        for key in ('text', 'content-desc'):
            if node.get(key) in LABELS and node.get('class') != 'android.widget.EditText':
                safe[key] = node.get(key)
        node.attrib.clear()
        node.attrib.update(safe)
    return ET.tostring(tree, encoding='unicode')


def _validate_device(serial, avd):
    if adb_call(serial, 'shell', 'getprop ro.boot.qemu.avd_name').strip() != avd:
        raise RuntimeError('Selected AVD does not match --avd')
    if 'package:' not in adb_call(serial, 'shell', 'pm', 'path', PACKAGE):
        raise RuntimeError('Tinder is not installed')


def _save_snapshot(xml, state, output):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = folder / f'{state}.xml'
    fixture.write_text(sanitized_xml(xml))
    (folder / 'status.json').write_text(json.dumps({'state': state,
                                                    'app': PACKAGE,
                                                    'fixture': fixture.name}, indent=2))


def _selected_photo_count(xml):
    nodes = [n for n in ET.fromstring(xml).iter('node') if n.get('package') in MEDIA_PACKAGES]
    orders = [n.get('text') for n in nodes if n.get('resource-id', '').endswith(':id/selected_order')]
    expected = [str(i) for i in range(1, len(orders) + 1)]
    if sorted(orders) != expected:
        raise RuntimeError('Photo picker has an unexpected partial selection; review it manually')
    return len(orders)


def run_signup(serial, avd, output, provider, *, accept_terms=False,
               accept_sms_terms=False, accept_house_rules=False, first_name=None,
               birth_date=None, gender=None, show_gender_on_profile=None,
               relationship_goal=None, photos=(), decline_notifications=False,
               allow_notifications=False, allow_location=False,
               pause_private_inputs=False, max_steps=50, transition_delay=1.0):
    """Run only the recorded signup path, stopping at every human-verification boundary."""
    _validate_device(serial, avd)
    if not (accept_terms and accept_sms_terms and accept_house_rules):
        raise RuntimeError('Signup runner requires explicit terms, SMS, and House Rules authorization')
    if gender not in ('Woman', 'Man') or not isinstance(show_gender_on_profile, bool):
        raise RuntimeError('Signup runner requires explicit gender and visibility choices')
    if relationship_goal not in RELATIONSHIP_GOALS:
        raise RuntimeError('Signup runner requires an explicit observed relationship goal')
    if allow_notifications and decline_notifications:
        raise RuntimeError('Choose either allow or decline notifications, not both')
    photos = tuple(Path(photo) for photo in photos)
    if len(photos) not in (0, 4):
        raise RuntimeError('Signup runner requires zero or four explicitly supplied photos')

    for _ in range(max_steps):
        xml = read_ui(serial)
        state = classify(xml)
        _save_snapshot(xml, state, output)
        print(f'Tinder signup: {state}', flush=True)

        if state in {'human-verification-manual-stop', 'locked-video-selfie-manual-stop'}:
            print('MANUAL STOP: human verification/CAPTCHA must be completed by the user; no challenge control was tapped.', flush=True)
            return 2
        if state == 'email-recovery-manual-stop':
            print('MANUAL STOP: choose email entry or Google account linking directly; nothing was selected.',
                  flush=True)
            return 2
        if state in {'verification-code-invalid', 'unknown'}:
            print('STOP: rejected or unlearned screen; no retry or UI action taken.', flush=True)
            return 2
        if state == 'notification-permission':
            if not (allow_notifications or decline_notifications):
                print('STOP: notification choice was not authorized.', flush=True)
                return 2
            choose_notifications(serial, allow_notifications)
        elif state == 'welcome-terms-and-login':
            continue_with_phone(serial)
        elif state == 'google-number-hint':
            dismiss_google_number_hint(serial)
        elif state == 'phone-entry':
            if pause_private_inputs:
                print('MANUAL STOP: phone number is private; no value or control was changed.', flush=True)
                return 2
            enter_phone(serial, provider, submit=True)
        elif state == 'verification-code':
            if pause_private_inputs:
                print('MANUAL STOP: verification code is private; no value or control was changed.', flush=True)
                return 2
            enter_code(serial, provider)
        elif state == 'house-rules':
            agree_house_rules(serial)
        elif state == 'first-name':
            if pause_private_inputs:
                print('MANUAL STOP: first name entry awaits direct input.', flush=True)
                return 2
            if first_name is None:
                first_name = getpass.getpass('First name (hidden; not saved): ').strip()
            enter_first_name(serial, first_name)
        elif state == 'profile-welcome':
            start_profile(serial)
        elif state == 'birth-date':
            if pause_private_inputs:
                print('MANUAL STOP: actual birth date entry awaits direct input.', flush=True)
                return 2
            if birth_date is None:
                birth_date = getpass.getpass('Actual birth date YYYY-MM-DD (hidden; not saved): ').strip()
            enter_birth_date(serial, birth_date)
        elif state == 'gender':
            select_gender(serial, gender, show_gender_on_profile)
        elif state == 'distance-preference':
            continue_default_distance(serial)
        elif state == 'relationship-goals':
            select_relationship_goal(serial, relationship_goal)
        elif state in {'lifestyle', 'personality'}:
            select_random_single_choice_traits(serial, state)
        elif state == 'interests':
            select_random_interests(serial)
        elif state in {'school', 'bio-and-prompt'}:
            skip_optional(serial)
        elif state == 'photos-manual-stop':
            count = sum(n.get('package') == PACKAGE and n.get('content-desc') == 'Profile photo, added'
                        for n in ET.fromstring(xml).iter('node'))
            if count == 0:
                if not photos:
                    print('MANUAL STOP: no approved four-photo library was supplied.', flush=True)
                    return 2
                open_photo_picker(serial)
            elif count == 4:
                continue_photos(serial)
            else:
                raise RuntimeError('Photo page has an unexpected partial upload; review it manually')
        elif state == 'android-photo-picker':
            selected = _selected_photo_count(xml)
            if selected < 4:
                pick_supplied_photo(serial, photos, selected)
            else:
                confirm_four_photos(serial, photos)
        elif state == 'photo-editor':
            finish_photo_edit(serial)
        elif state == 'location-rationale':
            if not allow_location:
                print('STOP: Tinder location access was not authorized.', flush=True)
                return 2
            allow_location_rationale(serial)
        elif state == 'location-permission':
            if not allow_location:
                print('STOP: Android foreground location access was not authorized.', flush=True)
                return 2
            allow_foreground_location(serial)
        elif state == 'location-accuracy-prompt':
            decline_optional_wifi_scanning(serial)
        else:
            raise RuntimeError(f'No signup runner action exists for observed state: {state}')
        if transition_delay:
            time.sleep(transition_delay)
    raise RuntimeError('Signup runner reached its step limit; stopped without further UI actions')


def observe(serial, avd, output, decline_notifications=False, allow_notifications=False):
    _validate_device(serial, avd)
    xml = read_ui(serial)
    state = classify(xml)
    # Fixtures omit editable values, account identifiers, OTPs and unknown labels.
    _save_snapshot(xml, state, output)
    print(f'Tinder screen: {state}', flush=True)
    if state == 'notification-permission' and (decline_notifications or allow_notifications):
        choose_notifications(serial, allow_notifications)
        return 0
    if state == 'welcome-terms-and-login':
        print('Login choices: Google, Phone Number, Line, Email. Continue accepts Tinder terms; awaiting user choice and confirmation.')
    elif state == 'house-rules':
        print('House Rules require user confirmation; no agreement tapped.')
    elif state == 'first-name':
        print('First name is public and cannot be changed later; awaiting user-provided name. No field filled.')
    elif state == 'birth-date':
        print('Birth date requires user-provided details; no date entered or submitted.')
    elif state == 'gender':
        print('Awaiting user gender selection and profile visibility choice; no option selected.')
    elif state == 'relationship-goals':
        print('Awaiting user relationship goal; no option selected.')
    elif state == 'photos-manual-stop':
        count = sum(n.get('package') == PACKAGE and n.get('content-desc') == 'Profile photo, added'
                    for n in ET.fromstring(xml).iter('node'))
        print(f'Photo boundary: {count} added photos displayed. No onboarding Next or completion action taken by observer.')
    elif state in {'human-verification-manual-stop', 'locked-video-selfie-manual-stop'}:
        print('MANUAL STOP: human verification/CAPTCHA requires the user. No challenge control was tapped and no retry or bypass was attempted.')
    elif state == 'unknown':
        print('Unlearned screen: no automatic action taken. Inspect it before adding a handler.')
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--decline-notifications', action='store_true')
    parser.add_argument('--allow-notifications', action='store_true')
    parser.add_argument('--pause-at-private-input', action='store_true',
                        help='Stop before phone, SMS, name, or birth-date entry')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--run-signup', action='store_true', help='Run the recorded flow until a CAPTCHA, human-verification, rejection, or unknown screen')
    action.add_argument('--enter-phone', action='store_true', help='Fill and verify phone field only; does not submit')
    action.add_argument('--submit-phone', action='store_true',
                        help='Submit an already filled ten-digit US phone field')
    action.add_argument('--enter-code', action='store_true', help='Privately enter the observed six-digit verification code')
    action.add_argument('--enter-email', action='store_true', help='Privately enter the observed recovery email without Google linking')
    action.add_argument('--agree-house-rules', action='store_true', help='Accept House Rules only after explicit user agreement')
    action.add_argument('--enter-name', action='store_true', help='Privately prompt for user-supplied first name and tap Next')
    action.add_argument('--start-profile', action='store_true', help='Continue the observed profile welcome screen')
    action.add_argument('--enter-birth-date', action='store_true', help='Privately prompt for actual adult birth date (YYYY-MM-DD) and tap Next')
    action.add_argument('--select-gender', choices=('Woman', 'Man'), help='Apply explicitly supplied gender and visibility choices')
    action.add_argument('--continue-default-distance', action='store_true', help='Keep observed 50-mile default and continue')
    action.add_argument('--relationship-goal', choices=sorted(RELATIONSHIP_GOALS), help='Choose an explicitly authorized goal and continue')
    action.add_argument('--skip-optional', action='store_true', help='Skip a reviewed optional profile question without inventing details')
    action.add_argument('--randomize-profile-traits', action='store_true', help='Select one answer per single-choice trait or 2-3 interests, then continue')
    action.add_argument('--open-photo-picker', action='store_true', help='Open first empty photo slot without tapping onboarding Next')
    action.add_argument('--pick-photo-index', type=int, help='Select one zero-based visible thumbnail after exact supplied-library hash verification')
    action.add_argument('--confirm-four-photos', action='store_true', help='Tap picker Add (4) only after exact supplied-library and selection checks')
    action.add_argument('--finish-photo-edit', action='store_true', help='Finish observed four-photo edit only; never tap onboarding Next')
    action.add_argument('--continue-photos', action='store_true', help='Explicitly authorized Next from the observed four-photo page; inspect afterward')
    action.add_argument('--allow-location-rationale', action='store_true', help='Tap Tinder location explanation Allow after explicit authorization')
    action.add_argument('--allow-foreground-location', action='store_true', help='Grant Tinder location while using the app, after explicit authorization')
    action.add_argument('--decline-wifi-scanning', action='store_true', help='Decline separate device-wide Wi-Fi scanning prompt without revoking app location')
    parser.add_argument('--photo', type=Path, action='append', default=[], help='Explicitly supplied local photo; repeat for complete verified library')
    parser.add_argument('--gender-visibility', choices=('show', 'hide'), help='Required with --select-gender')
    parser.add_argument('--accept-terms', action='store_true', help='Authorize Continue with Phone Number and the displayed Tinder terms during --run-signup')
    parser.add_argument('--accept-sms-terms', action='store_true', help='Authorize phone Next and the displayed SMS terms during --run-signup')
    parser.add_argument('--accept-house-rules', action='store_true', help='Authorize the displayed House Rules during --run-signup')
    parser.add_argument('--allow-location', action='store_true', help='Authorize foreground Tinder location during --run-signup; never enables device-wide Wi-Fi scanning')
    parser.add_argument('--signup-gender', choices=('Woman', 'Man'), help='Explicit gender choice for --run-signup')
    parser.add_argument('--signup-gender-visibility', choices=('show', 'hide'), help='Explicit gender visibility for --run-signup')
    parser.add_argument('--signup-relationship-goal', choices=sorted(RELATIONSHIP_GOALS), help='Explicit relationship goal for --run-signup')
    args = parser.parse_args()
    if args.allow_notifications and args.decline_notifications:
        parser.error('Choose only one notification permission action')
    if bool(args.select_gender) != bool(args.gender_visibility):
        parser.error('--select-gender and --gender-visibility must be supplied together')
    if args.submit_phone and not args.accept_sms_terms:
        parser.error('--submit-phone requires --accept-sms-terms')
    if (args.pick_photo_index is not None or args.confirm_four_photos) and not args.photo:
        parser.error('Photo selection requires explicit --photo paths for the complete supplied library')
    if args.run_signup:
        verify_phone_setup(args.serial, args.avd, PACKAGE)
        missing = [flag for flag, present in (
            ('--accept-terms', args.accept_terms),
            ('--accept-sms-terms', args.accept_sms_terms),
            ('--accept-house-rules', args.accept_house_rules),
            ('--signup-gender', args.signup_gender),
            ('--signup-gender-visibility', args.signup_gender_visibility),
            ('--signup-relationship-goal', args.signup_relationship_goal),
        ) if not present]
        if missing:
            parser.error('--run-signup requires ' + ', '.join(missing))
        if len(args.photo) not in (0, 4):
            parser.error('--run-signup requires zero or four --photo paths')
        return run_signup(
            args.serial, args.avd, args.output, ManualCredentials(),
            accept_terms=args.accept_terms,
            accept_sms_terms=args.accept_sms_terms,
            accept_house_rules=args.accept_house_rules,
            gender=args.signup_gender,
            show_gender_on_profile=args.signup_gender_visibility == 'show',
            relationship_goal=args.signup_relationship_goal,
            photos=args.photo,
            decline_notifications=args.decline_notifications,
            allow_notifications=args.allow_notifications,
            allow_location=args.allow_location,
            pause_private_inputs=args.pause_at_private_input,
        )
    mutations = (args.enter_phone, args.submit_phone, args.enter_code, args.enter_email,
                 args.agree_house_rules, args.enter_name,
                 args.start_profile, args.enter_birth_date, args.select_gender,
                 args.continue_default_distance, args.relationship_goal, args.skip_optional,
                 args.randomize_profile_traits,
                 args.open_photo_picker, args.pick_photo_index is not None,
                 args.confirm_four_photos, args.finish_photo_edit, args.continue_photos,
                 args.allow_location_rationale, args.allow_foreground_location, args.decline_wifi_scanning)
    if any(mutations):
        if adb_call(args.serial, 'shell', 'getprop ro.boot.qemu.avd_name').strip() != args.avd:
            raise RuntimeError('Selected AVD does not match --avd')
        if args.decline_wifi_scanning:
            decline_optional_wifi_scanning(args.serial)
        elif args.allow_foreground_location:
            allow_foreground_location(args.serial)
        elif args.allow_location_rationale:
            allow_location_rationale(args.serial)
        elif args.continue_photos:
            continue_photos(args.serial)
        elif args.open_photo_picker:
            open_photo_picker(args.serial)
        elif args.pick_photo_index is not None:
            pick_supplied_photo(args.serial, args.photo, args.pick_photo_index)
        elif args.confirm_four_photos:
            confirm_four_photos(args.serial, args.photo)
        elif args.finish_photo_edit:
            finish_photo_edit(args.serial)
        elif args.randomize_profile_traits:
            randomize_current_traits(args.serial)
        elif args.skip_optional:
            skip_optional(args.serial)
        elif args.relationship_goal:
            select_relationship_goal(args.serial, args.relationship_goal)
        elif args.select_gender:
            select_gender(args.serial, args.select_gender, args.gender_visibility == 'show')
        elif args.continue_default_distance:
            continue_default_distance(args.serial)
        elif args.enter_birth_date:
            enter_birth_date(args.serial, getpass.getpass('Actual birth date YYYY-MM-DD (hidden; not saved): ').strip())
        elif args.start_profile:
            start_profile(args.serial)
        elif args.enter_name:
            enter_first_name(args.serial, getpass.getpass('First name (hidden; not saved): ').strip())
        elif args.agree_house_rules:
            agree_house_rules(args.serial)
        elif args.submit_phone:
            submit_existing_phone(args.serial)
        elif args.enter_phone:
            enter_phone(args.serial, ManualCredentials())
        elif args.enter_code:
            enter_code(args.serial, ManualCredentials())
        else:
            enter_email(args.serial, getpass.getpass('Recovery email (hidden; not saved): ').strip())
    return observe(args.serial, args.avd, args.output, args.decline_notifications,
                   args.allow_notifications)


if __name__ == '__main__':
    raise SystemExit(main())
