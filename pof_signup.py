#!/usr/bin/env python3
"""Record and safely resume the observed Plenty of Fish onboarding flow.

The helper only automates the two Android permissions that the caller explicitly
authorizes. Account terms, credentials, SMS verification, photos, CAPTCHA and
identity checks are always manual stops. Saved XML removes entered values and
keeps only reviewed static labels and structural attributes.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from setup_ui import adb_call, read_ui
from phone_setup_guard import verify_phone_setup

PACKAGE = 'com.pof.android'
PERMISSION_PACKAGES = {
    'com.google.android.permissioncontroller',
    'com.android.permissioncontroller',
}
MEDIA_PACKAGES = {'com.google.android.providers.media.module',
                  'com.android.providers.media.module'}

# Labels observed in POF 5.70.1.1516767. Dynamic profile data is intentionally
# absent so it cannot enter committed fixtures.
LABELS = {
    'Allow POF to send you notifications?', 'Allow', 'Don’t allow', "Don't allow",
    'Create account', 'Sign in', 'What’s your first name?', "What's your first name?",
    'Next', 'Woman', 'Man', 'Non-binary', 'Show my gender on my profile',
    'What is your ethnicity?', 'Caucasian', 'Allow location',
    'Allow POF to access this device’s location?',
    "Allow POF to access this device's location?", 'Precise', 'Approximate',
    'While using the app', 'Only this time', 'Country', 'Postal code',
    'When is your birthday?', 'Email address', 'Password', 'Terms of Service',
    'Privacy Policy', 'Account created', 'Who are you looking for?',
    'Dating preferences', 'About you', 'More details', 'Lifestyle', 'Family',
    'Birth order', 'Headline', 'About me', 'Conversation topic', 'Interests',
    'Verify your phone number', 'Phone number', 'Enter verification code',
    'Resend code', 'Show those pearly whites.',
    'Time to share that lovely face with the world.', 'Remember...',
    'Show your face. People want to see you!',
    'Put the face filters away. They’re so last year.',
    'Keep your pants...and top on.',
    'Photos with your mini-me should also include you.',
    'Upload', 'Add photo', 'Take photo', 'Not now',
    'This app can only access the photos you select', 'Photos', 'Albums', 'Recent',
    'Rotate', 'Uploading photo...', 'Add a profile photo, and then some.',
    'Profile Picture', 'Get Selfie-verified', 'Badge preview', 'Selfie-verified',
    'Get verified', 'Skip', 'Get out there, and meet new people!',
    'There’s just one more thing we need to do.', "There's just one more thing we need to do.",
    'The Pledge', 'Be real.', 'Be kind.', 'Be respectful.', 'Be safe.', 'Got it',
    'Double your Chances with POF Prestige', 'Continue', 'Continue as free',
    'Age and distance filters are here!',
    'Control who you see with age and distance filters.', 'Set filters', 'Maybe later',
}

MANUAL_STATES = {
    'credentials-and-terms-manual-stop', 'phone-entry-manual-stop',
    'verification-code-manual-stop', 'photo-manual-stop', 'photo-source-manual-stop',
    'android-photo-picker-manual-stop', 'photo-crop-manual-stop',
    'optional-selfie-verification-manual-stop', 'pledge-manual-stop',
    'human-verification-manual-stop', 'unknown',
}


def _values(nodes, packages=None):
    return ' '.join(
        value for node in nodes
        if packages is None or node.get('package') in packages
        for value in (node.get('text', ''), node.get('content-desc', '')) if value
    ).casefold()


def classify(xml):
    """Classify one observed POF/Android screen without reading edit values."""
    nodes = list(ET.fromstring(xml).iter('node'))
    app = _values(nodes, {PACKAGE})
    permissions = _values(nodes, PERMISSION_PACKAGES)
    google = _values(nodes, {'com.google.android.gms'})
    media = _values(nodes, MEDIA_PACKAGES)
    resource_ids = {node.get('resource-id', '') for node in nodes
                    if node.get('package') == PACKAGE}

    if 'this app can only access the photos you select' in media and 'photos' in media:
        return 'android-photo-picker-manual-stop'
    if 'cloud media app' in _values(nodes, {'com.android.settings'}):
        return 'system-cloud-media-settings'

    challenge_markers = ('captcha', 'recaptcha', "i'm not a robot", 'i am not a robot',
                         'prove you are human', 'verify you are human', 'human verification',
                         'video selfie', 'face verification', 'photo verification')
    if any(marker in app for marker in challenge_markers):
        return 'human-verification-manual-stop'
    if 'allow pof to send you notifications?' in permissions:
        return 'notification-permission'
    if 'allow pof to access this device' in permissions and 'while using the app' in permissions:
        return 'location-permission'
    if 'save password?' in google and 'not now' in google:
        return 'password-manager-prompt'
    if {PACKAGE + ':id/home_navigation_meet_me',
            PACKAGE + ':id/meet_me_card_stack_view'} <= resource_ids:
        return 'main-feed-complete'
    if 'age and distance filters are here' in app and 'maybe later' in app:
        return 'first-run-filters-tip'
    if 'pof prestige' in app and 'continue as free' in app:
        return 'prestige-upsell'
    if (('the pledge' in app and 'be real' in app) or
            all(label in app for label in ('be real.', 'be kind.', 'be respectful.',
                                           'be safe.', 'got it'))):
        return 'pledge-manual-stop'
    if 'get out there, and meet new people' in app and 'one more thing' in app:
        return 'profile-success'
    if 'get selfie-verified' in app and 'get verified' in app and 'skip' in app:
        return 'optional-selfie-verification-manual-stop'
    if 'add a profile photo, and then some' in app and 'profile picture' in app:
        return 'photo-gallery-manual-stop'
    if 'uploading photo' in app:
        return 'photo-upload-in-progress'
    if 'upload' in app and 'rotate' in app:
        return 'photo-crop-manual-stop'
    if 'add photo' in app and 'take photo' in app and 'remember' in app:
        return 'photo-source-manual-stop'
    if 'share that lovely face' in app and ('show those pearly whites' in app or 'upload' in app):
        return 'photo-manual-stop'
    if 'enter verification code' in app or ('verification code' in app and 'resend' in app):
        return 'verification-code-manual-stop'
    if 'verify your phone number' in app or ('phone number' in app and 'send code' in app):
        return 'phone-entry-manual-stop'
    if 'email address' in app and 'password' in app and ('terms' in app or 'privacy' in app):
        return 'credentials-and-terms-manual-stop'
    if 'what’s your first name' in app or "what's your first name" in app:
        return 'first-name'
    if 'show my gender' in app and 'woman' in app and 'man' in app:
        return 'gender'
    if 'ethnicity' in app:
        return 'ethnicity'
    if 'allow location' in app and 'postal code' not in app:
        return 'location-rationale'
    if 'postal code' in app and 'country' in app:
        return 'location-details'
    if 'birthday' in app:
        return 'birthday'
    if 'account created' in app:
        return 'account-created'
    if 'who are you looking for' in app:
        return 'seeking-gender'
    if 'dating preferences' in app:
        return 'dating-preferences'
    if 'more details' in app:
        return 'more-details'
    if 'about you' in app:
        return 'about-you'
    if 'lifestyle' in app:
        return 'lifestyle'
    if 'birth order' in app:
        return 'birth-order'
    if 'family' in app:
        return 'family'
    if 'headline' in app:
        return 'headline'
    if 'conversation topic' in app:
        return 'conversation-topic'
    if 'about me' in app or 'tell us about yourself' in app:
        return 'bio'
    if 'interests' in app:
        return 'interests'
    if 'create account' in app and 'sign in' in app:
        return 'welcome'
    return 'unknown'


def sanitized_xml(xml):
    """Remove PII, credentials, codes and unreviewed text from a UI dump."""
    tree = ET.fromstring(xml)
    permitted = {'package', 'class', 'bounds', 'enabled', 'clickable', 'checkable',
                 'checked', 'selected', 'scrollable', 'password'}
    for node in tree.iter('node'):
        safe = {key: value for key, value in node.attrib.items() if key in permitted}
        resource = node.get('resource-id', '')
        if re.fullmatch(r'[A-Za-z0-9_.]+:id/[A-Za-z0-9_]+', resource):
            safe['resource-id'] = resource
        for key in ('text', 'content-desc'):
            value = node.get(key)
            if value in LABELS and node.get('class') != 'android.widget.EditText':
                safe[key] = value
        node.attrib.clear()
        node.attrib.update(safe)
    return ET.tostring(tree, encoding='unicode')


def _validate_device(serial, avd):
    if adb_call(serial, 'shell', 'getprop ro.boot.qemu.avd_name').strip() != avd:
        raise RuntimeError('Selected AVD does not match --avd')
    if 'package:' not in adb_call(serial, 'shell', 'pm', 'path', PACKAGE):
        raise RuntimeError('Plenty of Fish is not installed')


def _save_snapshot(xml, state, output):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = folder / f'{state}.xml'
    fixture.write_text(sanitized_xml(xml))
    (folder / 'status.json').write_text(json.dumps({
        'state': state, 'app': PACKAGE, 'fixture': fixture.name,
    }, indent=2) + '\n')


def _tap_exact(serial, xml, *, package, text, resource_id=None):
    root = ET.fromstring(xml)
    parents = {child: parent for parent in root.iter() for child in parent}
    matches = [node for node in root.iter('node')
               if node.get('package') == package and node.get('text') == text and
               (resource_id is None or node.get('resource-id') == resource_id)]
    if len(matches) != 1:
        raise RuntimeError(f'Expected one exact {text!r} control')
    target = matches[0]
    while target.get('clickable') != 'true':
        target = parents.get(target)
        if target is None or target.get('package') != package:
            raise RuntimeError(f'{text!r} has no package-owned clickable control')
    if target.get('enabled') != 'true':
        raise RuntimeError(f'{text!r} control is disabled')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', target.get('bounds', ''))
    if not match:
        raise RuntimeError(f'{text!r} control bounds unavailable')
    left, top, right, bottom = map(int, match.groups())
    adb_call(serial, 'shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2))


def allow_notifications(serial):
    xml = read_ui(serial)
    if classify(xml) != 'notification-permission':
        raise RuntimeError('Expected observed POF notification permission')
    _tap_exact(serial, xml, package=next(p for p in PERMISSION_PACKAGES if p in xml),
               text='Allow',
               resource_id='com.android.permissioncontroller:id/permission_allow_button')
    print('Allowed POF notifications.', flush=True)


def allow_location(serial):
    xml = read_ui(serial)
    state = classify(xml)
    if state == 'location-rationale':
        _tap_exact(serial, xml, package=PACKAGE, text='Allow')
        print('Accepted POF location explanation; Android permission is next.', flush=True)
        return
    if state != 'location-permission':
        raise RuntimeError('Expected observed POF location explanation or Android permission')
    package = next(p for p in PERMISSION_PACKAGES if p in xml)
    _tap_exact(serial, xml, package=package, text='While using the app',
               resource_id='com.android.permissioncontroller:id/permission_allow_foreground_only_button')
    print('Allowed precise foreground location; no background access granted.', flush=True)


def accept_pledge(serial):
    """Accept the POF conduct pledge only after explicit caller authorization."""
    xml = read_ui(serial)
    if classify(xml) != 'pledge-manual-stop':
        raise RuntimeError('Expected observed POF community Pledge')
    _tap_exact(serial, xml, package=PACKAGE, text='Got it')
    print('Accepted the explicitly authorized POF community Pledge.', flush=True)


def continue_as_free(serial):
    """Dismiss the optional Prestige offer without starting a purchase."""
    xml = read_ui(serial)
    if classify(xml) != 'prestige-upsell':
        raise RuntimeError('Expected observed POF Prestige offer')
    _tap_exact(serial, xml, package=PACKAGE, text='Continue as free')
    print('Continued with the free POF account; no purchase was started.', flush=True)


def dismiss_filters_tip(serial):
    xml = read_ui(serial)
    if classify(xml) != 'first-run-filters-tip':
        raise RuntimeError('Expected observed age/distance filters tip')
    _tap_exact(serial, xml, package=PACKAGE, text='Maybe later')
    print('Dismissed the optional first-run filters tip.', flush=True)


def observe(serial, avd, output):
    _validate_device(serial, avd)
    xml = read_ui(serial)
    if not xml:
        raise RuntimeError('No Android UI hierarchy was returned')
    state = classify(xml)
    _save_snapshot(xml, state, output)
    print(f'POF screen: {state}; sanitized snapshot saved.', flush=True)
    return state


def run_signup(serial, avd, output, *, notifications=False, location=False,
               dismiss_password_save=False, accept_community_pledge=False,
               free_account=False, dismiss_tip=False):
    """Advance only explicitly authorized permissions; pause everywhere else."""
    _validate_device(serial, avd)
    for _ in range(20):
        xml = read_ui(serial)
        state = classify(xml)
        _save_snapshot(xml, state, output)
        print(f'POF screen: {state}', flush=True)
        if state == 'notification-permission' and notifications:
            allow_notifications(serial)
        elif state in {'location-rationale', 'location-permission'} and location:
            allow_location(serial)
        elif state == 'password-manager-prompt' and dismiss_password_save:
            _tap_exact(serial, xml, package='com.google.android.gms', text='Not now')
            print('Dismissed the optional Google password-save prompt.', flush=True)
        elif state == 'pledge-manual-stop' and accept_community_pledge:
            accept_pledge(serial)
        elif state == 'prestige-upsell' and free_account:
            continue_as_free(serial)
        elif state == 'first-run-filters-tip' and dismiss_tip:
            dismiss_filters_tip(serial)
        elif state == 'main-feed-complete':
            print('POF signup complete at the main feed; no feed action was taken.', flush=True)
            return 0
        else:
            reason = ('sensitive/manual boundary' if state in MANUAL_STATES else
                      'profile choice requiring direct review')
            print(f'Paused at {state}: {reason}; no control was tapped.', flush=True)
            return 2
        time.sleep(1)
    raise RuntimeError('Action limit reached; inspect the device before resuming')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--run-signup', action='store_true')
    parser.add_argument('--allow-notifications', action='store_true')
    parser.add_argument('--allow-location', action='store_true')
    parser.add_argument('--dismiss-password-save', action='store_true')
    parser.add_argument('--accept-pledge', action='store_true',
                        help='Accept the reviewed POF community Pledge')
    parser.add_argument('--continue-as-free', action='store_true',
                        help='Decline the reviewed Prestige offer without a purchase')
    parser.add_argument('--dismiss-filters-tip', action='store_true')
    args = parser.parse_args()
    if args.run_signup:
        verify_phone_setup(args.serial, args.avd, PACKAGE)
        return run_signup(args.serial, args.avd, args.output,
                          notifications=args.allow_notifications,
                          location=args.allow_location,
                          dismiss_password_save=args.dismiss_password_save,
                          accept_community_pledge=args.accept_pledge,
                          free_account=args.continue_as_free,
                          dismiss_tip=args.dismiss_filters_tip)
    observe(args.serial, args.avd, args.output)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print('\nPOF capture paused; device state is retained.')
        raise SystemExit(2)
    except (RuntimeError, subprocess.SubprocessError, ET.ParseError) as error:
        raise SystemExit(f'POF signup: {error}')
