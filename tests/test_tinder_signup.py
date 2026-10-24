import tempfile
import unittest
from unittest.mock import patch, Mock
from xml.sax.saxutils import escape

import tinder_signup as tinder


def welcome():
    return ('<hierarchy><node package="com.tinder" text="' + tinder.TERMS + '"/>'
            '<node package="com.tinder" text="Continue with Phone Number"/></hierarchy>')


def otp(value=''):
    fields = ''.join(
        f'<node package="com.tinder" class="android.widget.EditText" '
        f'resource-id="com.tinder:id/otp_input_view_{i}" '
        f'text="{value[i] if value else ""}" bounds="[0,0][100,100]"/>'
        for i in range(6))
    return '<hierarchy><node package="com.tinder" text="Enter your code"/>' + fields + '</hierarchy>'


def birthday_screen(value='MMDDYYYY'):
    return '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>'
        for label in ('Your b-day?', 'Your profile shows your age, not your birth date.', 'Next')) + ''.join(
        f'<node package="com.tinder" class="android.widget.EditText" text="{digit}" bounds="[{i*100},0][{i*100+80},80]"/>'
        for i, digit in enumerate(value)) + '</hierarchy>'


def gender_screen(visible=False, next_enabled=True):
    labels = ('What’s your gender?', 'Woman', 'Man', 'Show my gender on my profile', 'Next')
    ids = ('onboarding_binary_gender_title', 'gender_female_selection_button',
           'gender_male_selection_button', 'show_gender_on_profile_checkbox', 'text_button')
    return '<hierarchy>' + ''.join(
        f'<node package="com.tinder" text="{label}" resource-id="com.tinder:id/{rid}" '
        f'bounds="[0,{i*100}][100,{i*100+80}]" enabled="{str(next_enabled if i == 4 else True).lower()}" '
        f'clickable="true" checked="{str(visible if i == 3 else False).lower()}"/>'
        for i, (label, rid) in enumerate(zip(labels, ids))) + '</hierarchy>'


def trait_screen(state, progress=0):
    if state == 'lifestyle':
        title = 'Do their habits match yours? You go first.'
        questions = tinder.LIFESTYLE_QUESTIONS
        options = [value for values in tinder.LIFESTYLE_OPTIONS.values() for value in values]
    else:
        title = 'What else makes you–you?'
        questions = tinder.PERSONALITY_QUESTIONS
        options = [value for values in tinder.PERSONALITY_OPTIONS.values() for value in values]
    return ('<hierarchy><node package="com.tinder" resource-id="com.tinder:id/title_textview"/>'
            + ''.join(f'<node package="com.tinder" text="{escape(label)}"/>' for label in [title, 'Skip', *questions])
            + ''.join(f'<node package="com.tinder" content-desc="{escape(label)}"/>' for label in options)
            + f'<node package="com.tinder" text="Next {progress}/4" resource-id="com.tinder:id/text_button" enabled="true" clickable="true"/>'
            + '</hierarchy>')


def interests_screen(progress=0):
    return ('<hierarchy><node package="com.tinder" resource-id="com.tinder:id/title_textview"/>'
            + ''.join(f'<node package="com.tinder" text="{escape(label)}"/>' for label in
                      ('What are you into?', tinder.INTERESTS_BODY, 'Skip'))
            + ''.join(f'<node package="com.tinder" content-desc="{escape(label)}"/>' for label in tinder.INTEREST_OPTIONS)
            + f'<node package="com.tinder" text="Next {progress}/10" resource-id="com.tinder:id/text_button" enabled="true" clickable="true"/>'
            + '</hierarchy>')


class TinderTests(unittest.TestCase):
    def test_random_single_choice_traits_select_one_per_category(self):
        rng = Mock()
        rng.choice.side_effect = lambda values: values[0]
        screens = [trait_screen('personality', progress) for progress in range(5)]
        with patch.object(tinder, 'read_ui', side_effect=screens), \
                patch.object(tinder, 'tap_label') as tap, \
                patch.object(tinder, 'tap_resource') as next_button:
            chosen = tinder.select_random_single_choice_traits('test', 'personality', rng)
        self.assertEqual(len(chosen), 4)
        self.assertEqual(tap.call_count, 4)
        self.assertEqual(chosen, [values[0] for values in tinder.PERSONALITY_OPTIONS.values()])
        next_button.assert_called_once_with('test', screens[-1], 'text_button')

    def test_random_multi_choice_interests_selects_two_or_three_distinct(self):
        rng = Mock()
        rng.randint.return_value = 3
        rng.sample.side_effect = lambda values, count: values[:count]
        screens = [interests_screen(progress) for progress in range(4)]
        with patch.object(tinder, 'read_ui', side_effect=screens), \
                patch.object(tinder, 'tap_label') as tap, \
                patch.object(tinder, 'tap_resource') as next_button:
            chosen = tinder.select_random_interests('test', rng)
        self.assertEqual(len(chosen), 3)
        self.assertEqual(len(set(chosen)), 3)
        self.assertEqual(tap.call_count, 3)
        next_button.assert_called_once_with('test', screens[-1], 'text_button')

    def test_random_traits_refuse_partial_selection_without_tapping(self):
        with patch.object(tinder, 'read_ui', return_value=trait_screen('lifestyle', 1)), \
                patch.object(tinder, 'tap_label') as tap, patch.object(tinder, 'tap_resource') as next_button:
            with self.assertRaisesRegex(RuntimeError, 'untouched observed'):
                tinder.select_random_single_choice_traits('test', 'lifestyle')
        tap.assert_not_called()
        next_button.assert_not_called()

    def test_captcha_and_human_verification_are_manual_stops(self):
        for label in ("Verify you're human", 'Complete this CAPTCHA', "I'm not a robot",
                      'Face verification required'):
            with self.subTest(label=label):
                xml = f'<hierarchy><node package="com.tinder" text="{label}"/></hierarchy>'
                self.assertEqual(tinder.classify(xml), 'human-verification-manual-stop')

    def test_signup_runner_connects_observed_states_and_stops_before_video_selfie(self):
        google = '<hierarchy><node package="com.google.android.gms" text="Choose a phone number"/></hierarchy>'
        locked = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in
            ('We need to know it’s you', tinder.LOCKED_MESSAGE, 'Complete a video selfie to get back in', 'Get verified')) + '</hierarchy>'
        def call(serial, *args):
            if args == ('shell', 'getprop ro.boot.qemu.avd_name'):
                return 'Test'
            if args == ('shell', 'pm', 'path', tinder.PACKAGE):
                return 'package:/data/app/tinder/base.apk'
            raise AssertionError('Unexpected device mutation')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(tinder, 'read_ui', side_effect=[welcome(), google, locked]), \
                patch.object(tinder, 'adb_call', side_effect=call), \
                patch.object(tinder, 'continue_with_phone') as phone, \
                patch.object(tinder, 'dismiss_google_number_hint') as dismiss:
            result = tinder.run_signup(
                'test', 'Test', folder, Mock(), accept_terms=True, accept_sms_terms=True,
                accept_house_rules=True, gender='Woman', show_gender_on_profile=True,
                relationship_goal='Still figuring it out', photos=('1', '2', '3', '4'),
                transition_delay=0)
        self.assertEqual(result, 2)
        phone.assert_called_once_with('test')
        dismiss.assert_called_once_with('test')

    def test_signup_runner_never_mutates_a_captcha_screen(self):
        challenge = '<hierarchy><node package="com.tinder" text="Complete this CAPTCHA"/></hierarchy>'
        def call(serial, *args):
            if args == ('shell', 'getprop ro.boot.qemu.avd_name'):
                return 'Test'
            if args == ('shell', 'pm', 'path', tinder.PACKAGE):
                return 'package:/data/app/tinder/base.apk'
            raise AssertionError('Unexpected device mutation at CAPTCHA boundary')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(tinder, 'read_ui', return_value=challenge), \
                patch.object(tinder, 'adb_call', side_effect=call):
            result = tinder.run_signup(
                'test', 'Test', folder, Mock(), accept_terms=True, accept_sms_terms=True,
                accept_house_rules=True, gender='Woman', show_gender_on_profile=False,
                relationship_goal='Still figuring it out', photos=('1', '2', '3', '4'),
                transition_delay=0)
        self.assertEqual(result, 2)

    def test_signup_runner_randomizes_traits_instead_of_skipping(self):
        locked = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in
            ('We need to know it’s you', tinder.LOCKED_MESSAGE, 'Complete a video selfie to get back in', 'Get verified')) + '</hierarchy>'
        def call(serial, *args):
            if args == ('shell', 'getprop ro.boot.qemu.avd_name'):
                return 'Test'
            if args == ('shell', 'pm', 'path', tinder.PACKAGE):
                return 'package:/data/app/tinder/base.apk'
            raise AssertionError('Unexpected device mutation')
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(tinder, 'read_ui', side_effect=[trait_screen('personality'), locked]), \
                patch.object(tinder, 'adb_call', side_effect=call), \
                patch.object(tinder, 'select_random_single_choice_traits') as select, \
                patch.object(tinder, 'skip_optional') as skip:
            result = tinder.run_signup(
                'test', 'Test', folder, Mock(), accept_terms=True, accept_sms_terms=True,
                accept_house_rules=True, gender='Woman', show_gender_on_profile=False,
                relationship_goal='Still figuring it out', photos=('1', '2', '3', '4'),
                transition_delay=0)
        self.assertEqual(result, 2)
        select.assert_called_once_with('test', 'personality')
        skip.assert_not_called()

    def test_locked_video_selfie_screen_is_manual_stop_with_no_ui_mutations(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in
            ('We need to know it’s you', tinder.LOCKED_MESSAGE, 'Complete a video selfie to get back in', 'Get verified')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'locked-video-selfie-manual-stop')
        self.assertEqual(tinder.classify(xml.replace('com.tinder', 'other.app')), 'unknown')
        def call(serial, *args):
            if args == ('shell', 'getprop ro.boot.qemu.avd_name'):
                return 'Test'
            if args == ('shell', 'pm', 'path', tinder.PACKAGE):
                return 'package:/data/app/tinder/base.apk'
            raise AssertionError('Unexpected device mutation at verification boundary')
        with tempfile.TemporaryDirectory() as folder, patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'adb_call', side_effect=call):
            self.assertEqual(tinder.observe('test', 'Test', folder), 2)
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
            with self.assertRaisesRegex(RuntimeError, 'reviewed optional screen'):
                tinder.skip_optional('test')
        tap.assert_not_called()

    def test_wifi_scanning_decline_is_specific_and_does_not_change_app_grants(self):
        xml = '<hierarchy>' + ''.join('<node package="com.google.android.gms" text="' + label + '"/>'
            for label in (tinder.ACCURACY_MESSAGE, 'Wi‑Fi scanning', 'Turn on')) + '<node package="com.google.android.gms" text="No thanks" resource-id="android:id/button2" enabled="true" clickable="true" bounds="[0,0][100,100]"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'location-accuracy-prompt')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'adb_call') as call:
            tinder.decline_optional_wifi_scanning('test')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '50')
        self.assertEqual(tinder.classify(xml.replace('com.google.android.gms', 'other.app')), 'unknown')

    def test_location_permission_is_app_and_package_specific(self):
        xml = '<hierarchy><node package="com.google.android.permissioncontroller" text="' + tinder.LOCATION_PERMISSION + '"/><node package="com.google.android.permissioncontroller" text="While using the app" resource-id="com.android.permissioncontroller:id/permission_allow_foreground_only_button" enabled="true" clickable="true" bounds="[0,0][100,100]"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'location-permission')
        self.assertEqual(tinder.classify(xml.replace('Allow Tinder', 'Allow AnotherApp')), 'unknown')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'adb_call') as call:
            tinder.allow_foreground_location('test')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '50')
        with patch.object(tinder, 'read_ui', return_value=xml.replace('enabled="true"', 'enabled="false"')), patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'Foreground location control'):
                tinder.allow_foreground_location('test')
        call.assert_not_called()

    def test_location_rationale_uses_exact_allow_label_not_duplicated_resource(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in
            ('So, are you from around here?', tinder.LOCATION_BODY, 'Allow', 'How is my location used?')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'location-rationale')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_label') as tap:
            tinder.allow_location_rationale('test')
        tap.assert_called_once_with('test', xml, 'Allow')

    def test_photo_advance_requires_four_added_photos_and_explicit_action(self):
        xml = '<hierarchy><node package="com.tinder" resource-id="com.tinder:id/onboardingPhotoTitle" text="Add your recent pics"/>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in (tinder.PHOTOS_BODY, 'Next')) + '<node package="com.tinder" content-desc="Add photo"/>' + '<node package="com.tinder" content-desc="Profile photo, added"/>'*4 + '</hierarchy>'
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
            tinder.continue_photos('test')
        tap.assert_called_once_with('test', xml, 'text_button')
        with patch.object(tinder, 'read_ui', return_value=xml.replace('Profile photo, added', 'Image')), patch.object(tinder, 'tap_resource') as tap:
            with self.assertRaisesRegex(RuntimeError, 'four added photos'):
                tinder.continue_photos('test')
        tap.assert_not_called()

    def test_bio_prompt_screen_can_be_skipped_without_entering_text(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in
            ('Share more about yourself', tinder.BIO_BODY, 'About me', 'Select a prompt', 'Skip')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'bio-and-prompt')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
            tinder.skip_optional('test')
        tap.assert_called_once_with('test', xml, 'onboarding_skip_button')

    def test_four_photo_editor_done_is_not_onboarding_next(self):
        xml = '<hierarchy><node package="com.tinder" text="Edit photos"/><node package="com.tinder" text="Done"/><node package="com.tinder" content-desc="Zoomable Image"/>' + '<node package="com.tinder" content-desc="Image"/><node package="com.tinder" content-desc="Remove"/>' * 4 + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'photo-editor')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_label') as tap:
            tinder.finish_photo_edit('test')
        tap.assert_called_once_with('test', xml, 'Done')
        with patch.object(tinder, 'read_ui', return_value=welcome()), patch.object(tinder, 'tap_label') as tap:
            with self.assertRaisesRegex(RuntimeError, 'four-photo editor'):
                tinder.finish_photo_edit('test')
        tap.assert_not_called()

    def test_photo_picker_classification_excludes_capture_dates_from_fixtures(self):
        xml = '<hierarchy><node package="com.google.android.providers.media.module" text="' + tinder.PICKER_PRIVACY + '"/><node package="com.google.android.providers.media.module" content-desc="Photo taken on PRIVATE_DATE"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'android-photo-picker')
        self.assertNotIn('PRIVATE_DATE', tinder.sanitized_xml(xml))
        self.assertEqual(tinder.classify(xml.replace('com.google.android.providers.media.module', 'other.app')), 'unknown')

    def test_photo_hash_mismatch_never_selects_thumbnail(self):
        xml = '<hierarchy><node package="com.google.android.providers.media.module" text="' + tinder.PICKER_PRIVACY + '"/><node package="com.google.android.providers.media.module" content-desc="Photo taken on example" clickable="true" enabled="true" bounds="[0,0][100,100]"/></hierarchy>'
        with patch.object(tinder, 'read_ui', return_value=xml), \
                patch.object(tinder, 'verify_supplied_photo_library', side_effect=RuntimeError('hash mismatch')), \
                patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                tinder.pick_supplied_photo('test', ['photo.jpg'])
        call.assert_not_called()

    def test_photo_library_hashes_must_match_exact_supplied_set(self):
        from pathlib import Path
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / 'supplied.jpg'
            photo.write_bytes(b'example image fixture')
            digest = hashlib.sha256(photo.read_bytes()).hexdigest()
            rows = 'Row: 0 _data=/storage/emulated/0/Pictures/01.jpg\n'
            with patch.object(tinder, 'adb_call', side_effect=[rows, digest + '  /storage/emulated/0/Pictures/01.jpg\n']):
                self.assertEqual(tinder.verify_supplied_photo_library('test', [photo]), 1)
            with patch.object(tinder, 'adb_call', side_effect=[rows, '0'*64 + '  /storage/emulated/0/Pictures/01.jpg\n']):
                with self.assertRaisesRegex(RuntimeError, 'hashes differ'):
                    tinder.verify_supplied_photo_library('test', [photo])

    def test_picker_confirmation_requires_exactly_four_selected(self):
        package = 'com.google.android.providers.media.module'
        xml = '<hierarchy><node package="' + package + '" text="' + tinder.PICKER_PRIVACY + '"/><node package="' + package + '" content-desc="Photo taken on example"/>' + ''.join(
            f'<node package="{package}" resource-id="{package}:id/selected_order" text="{i}"/>' for i in range(1,5)) + f'<node package="{package}" resource-id="{package}:id/button_add" text="Add (4)" enabled="true" clickable="true" bounds="[0,0][100,100]"/></hierarchy>'
        with patch.object(tinder, 'read_ui', return_value=xml), \
                patch.object(tinder, 'verify_supplied_photo_library', return_value=4), \
                patch.object(tinder, 'adb_call') as call:
            tinder.confirm_four_photos('test', ['one','two','three','four'])
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '50')
        with patch.object(tinder, 'read_ui', return_value=xml.replace('text="4"', 'text="3"')), \
                patch.object(tinder, 'verify_supplied_photo_library', return_value=4), \
                patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'Exactly four selected'):
                tinder.confirm_four_photos('test', ['one','two','three','four'])
        call.assert_not_called()

    def test_optional_screen_classification_and_skip_are_guarded(self):
        cases = {
            'school': {'If school’s your thing…', 'Enter school name', 'Skip'},
            'lifestyle': tinder.LIFESTYLE_QUESTIONS | {'Do their habits match yours? You go first.', 'Skip'},
            'personality': tinder.PERSONALITY_QUESTIONS | {'What else makes you–you?', 'Skip'},
            'interests': {'What are you into?', tinder.INTERESTS_BODY, 'Skip'},
        }
        for state, labels in cases.items():
            rid = 'school_title' if state == 'school' else 'title_textview'
            xml = '<hierarchy><node package="com.tinder" resource-id="com.tinder:id/' + rid + '"/>' + ''.join(
                '<node package="com.tinder" text="' + label + '"/>' for label in labels) + '</hierarchy>'
            with self.subTest(state=state):
                self.assertEqual(tinder.classify(xml), state)
                with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
                    tinder.skip_optional('test')
                tap.assert_called_once_with('test', xml, 'onboarding_skip_button')
        with patch.object(tinder, 'read_ui', return_value=welcome()), patch.object(tinder, 'tap_resource') as tap:
            with self.assertRaisesRegex(RuntimeError, 'reviewed optional screen'):
                tinder.skip_optional('test')
        tap.assert_not_called()

    def test_compose_label_taps_enabled_parent_not_child_coordinates(self):
        xml = '<hierarchy><node package="com.tinder" enabled="true" clickable="true" bounds="[0,0][100,200]"><node package="com.tinder" text="Next" clickable="false" bounds="[40,40][60,60]"/></node></hierarchy>'
        with patch.object(tinder, 'adb_call') as call:
            tinder.tap_label('test', xml, 'Next')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '100')
        with patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                tinder.tap_label('test', xml.replace('enabled="true"', 'enabled="false"'), 'Next')
        call.assert_not_called()

    def test_relationship_handler_stops_if_screen_changes(self):
        with patch.object(tinder, 'read_ui', side_effect=['first', 'second']), \
                patch.object(tinder, 'classify', side_effect=['relationship-goals', 'unknown']), \
                patch.object(tinder, 'tap_label') as tap:
            tinder.select_relationship_goal('test', 'Still figuring it out')
        tap.assert_called_once_with('test', 'first', 'Still figuring it out')

    def test_photo_screen_is_manual_stop_and_cannot_be_skipped(self):
        xml = '<hierarchy><node package="com.tinder" resource-id="com.tinder:id/onboardingPhotoTitle" text="Add your recent pics"/>' + ''.join(
            '<node package="com.tinder" text="' + label + '"/>' for label in (tinder.PHOTOS_BODY, 'Next')) + '<node package="com.tinder" content-desc="Add photo"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'photos-manual-stop')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
            with self.assertRaisesRegex(RuntimeError, 'reviewed optional screen'):
                tinder.skip_optional('test')
        tap.assert_not_called()

    def test_relationship_goals_use_observed_accessibility_labels(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>'
            for label in ('What are you looking for?', tinder.GOALS_BODY, 'Next')) + ''.join(
            '<node package="com.tinder" content-desc="' + label + '"/>' for label in tinder.RELATIONSHIP_GOALS) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'relationship-goals')
        self.assertEqual(tinder.classify(xml.replace('com.tinder', 'other.app')), 'unknown')
        for label in tinder.RELATIONSHIP_GOALS:
            self.assertIn(label, tinder.sanitized_xml(xml))

    def test_distance_continues_only_observed_default(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>'
            for label in ('Your distance preference?', tinder.DISTANCE_BODY, 'Distance Preference', 'Next', '50 Mi')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'distance-preference')
        with patch.object(tinder, 'read_ui', return_value=xml), patch.object(tinder, 'tap_resource') as tap:
            tinder.continue_default_distance('test')
        tap.assert_called_once_with('test', xml, 'text_button')
        with patch.object(tinder, 'read_ui', return_value=xml.replace('50 Mi', '100 Mi')), patch.object(tinder, 'tap_resource') as tap:
            with self.assertRaisesRegex(RuntimeError, 'differs from observed default'):
                tinder.continue_default_distance('test')
        tap.assert_not_called()

    def test_gender_choice_enables_requested_visibility_before_next(self):
        with patch.object(tinder, 'read_ui', side_effect=[gender_screen(), gender_screen(), gender_screen(True)]), \
                patch.object(tinder, 'tap_resource') as tap:
            tinder.select_gender('test', 'Woman', True)
        self.assertEqual([c.args[2] for c in tap.call_args_list],
                         ['gender_female_selection_button', 'show_gender_on_profile_checkbox', 'text_button'])

    def test_gender_visibility_already_enabled_is_not_toggled_off(self):
        with patch.object(tinder, 'read_ui', side_effect=[gender_screen(True), gender_screen(True)]), \
                patch.object(tinder, 'tap_resource') as tap:
            tinder.select_gender('test', 'Woman', True)
        self.assertEqual([c.args[2] for c in tap.call_args_list], ['gender_female_selection_button', 'text_button'])

    def test_gender_transition_does_not_tap_unlearned_screen(self):
        with patch.object(tinder, 'read_ui', side_effect=[gender_screen(), welcome()]), \
                patch.object(tinder, 'tap_resource') as tap:
            tinder.select_gender('test', 'Woman', True)
        self.assertEqual(tap.call_count, 1)

    def test_disabled_resource_is_never_tapped(self):
        with patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                tinder.tap_resource('test', gender_screen(next_enabled=False), 'text_button')
        call.assert_not_called()

    def test_gender_requires_observed_labels_and_resource_ids(self):
        labels = ('What’s your gender?', 'Woman', 'Man', 'Show my gender on my profile', 'Next')
        ids = ('onboarding_binary_gender_title', 'gender_female_selection_button',
               'gender_male_selection_button', 'show_gender_on_profile_checkbox', 'text_button')
        xml = '<hierarchy>' + ''.join(f'<node package="com.tinder" text="{label}" resource-id="com.tinder:id/{rid}"/>'
            for label, rid in zip(labels, ids)) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'gender')
        self.assertEqual(tinder.classify(xml.replace('gender_male_selection_button', 'unexpected')), 'unknown')
        self.assertEqual(tinder.classify(xml.replace('com.tinder', 'other.app')), 'unknown')

    def test_birth_date_entry_checks_all_digits_before_next(self):
        with patch.object(tinder, 'read_ui', side_effect=[birthday_screen(), birthday_screen('05051990')]), \
                patch.object(tinder.subprocess, 'run') as run, \
                patch.object(tinder, 'button_center', return_value=(50, 150)), \
                patch.object(tinder, 'adb_call') as call:
            tinder.enter_birth_date('test', '1990-05-05')
        self.assertEqual(run.call_count, 8)
        self.assertEqual(''.join(c.kwargs['input'].split('input text ')[1].strip() for c in run.call_args_list), '05051990')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '150')
        self.assertNotIn('text="5"', tinder.sanitized_xml(birthday_screen('05051990')))

    def test_birth_date_mismatch_does_not_submit(self):
        with patch.object(tinder, 'read_ui', side_effect=[birthday_screen(), birthday_screen()]), \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'read-back did not match'):
                tinder.enter_birth_date('test', '1990-05-05')
        call.assert_not_called()

    def test_birth_date_rejects_invalid_or_underage_before_device_mutation(self):
        with patch.object(tinder, 'read_ui') as read:
            with self.assertRaises(ValueError):
                tinder.enter_birth_date('test', '1990-02-30')
            with self.assertRaisesRegex(RuntimeError, 'adult birth date'):
                tinder.enter_birth_date('test', tinder.date.today().isoformat())
        read.assert_not_called()

    def test_first_name_entry_checks_value_then_advances(self):
        xml = '<hierarchy><node package="com.tinder" text="What’s your first name?"/><node package="com.tinder" class="android.widget.EditText" resource-id="com.tinder:id/onboarding_name_edit_text" bounds="[0,0][100,100]" text=""/></hierarchy>'
        with patch.object(tinder, 'read_ui', side_effect=[xml, xml.replace('text=""', 'text="TestName"')]), \
                patch.object(tinder.subprocess, 'run') as run, \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder, 'button_center', return_value=(50, 150)):
            tinder.enter_first_name('test', 'TestName')
        self.assertNotIn('TestName', repr(run.call_args.args))
        self.assertEqual(run.call_args.kwargs['input'], 'input text TestName\n')
        self.assertEqual(call.call_args.args, ('test', 'shell', 'input', 'tap', '50', '150'))

    def test_first_name_mismatch_never_advances(self):
        xml = '<hierarchy><node package="com.tinder" text="What’s your first name?"/><node package="com.tinder" class="android.widget.EditText" resource-id="com.tinder:id/onboarding_name_edit_text" bounds="[0,0][100,100]" text=""/></hierarchy>'
        with patch.object(tinder, 'read_ui', return_value=xml), \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'adb_call'), \
                patch.object(tinder, 'button_center') as button:
            with self.assertRaisesRegex(RuntimeError, 'read-back did not match'):
                tinder.enter_first_name('test', 'TestName')
        button.assert_not_called()

    def test_profile_welcome_is_recognized_without_saving_name(self):
        xml = '<hierarchy><node package="com.tinder" text="Welcome, PrivateName!"/>' + ''.join(
            '<node package="com.tinder" text="' + label + '"/>'
            for label in (tinder.PROFILE_WELCOME, 'Let’s go', 'Edit name')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'profile-welcome')
        self.assertNotIn('PrivateName', tinder.sanitized_xml(xml))
        with patch.object(tinder, 'read_ui', return_value=xml), \
                patch.object(tinder, 'button_center', return_value=(50, 150)), \
                patch.object(tinder, 'adb_call') as call:
            tinder.start_profile('test')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '150')

    def test_birthday_requires_title_explanation_and_eight_fields(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>'
            for label in ('Your b-day?', 'Your profile shows your age, not your birth date.', 'Next'))
        fields = '<node package="com.tinder" class="android.widget.EditText"/>'
        self.assertEqual(tinder.classify(xml + fields * 8 + '</hierarchy>'), 'birth-date')
        self.assertEqual(tinder.classify(xml + fields * 7 + '</hierarchy>'), 'unknown')

    def test_first_name_requires_observed_label_and_field(self):
        xml = '<hierarchy><node package="com.tinder" text="What’s your first name?"/><node package="com.tinder" class="android.widget.EditText" resource-id="com.tinder:id/onboarding_name_edit_text" text="PrivateName"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'first-name')
        self.assertEqual(tinder.classify(xml.replace('com.tinder', 'other.app')), 'unknown')
        self.assertNotIn('PrivateName', tinder.sanitized_xml(xml))

    def test_agreement_action_refuses_unexpected_screen(self):
        with patch.object(tinder, 'read_ui', return_value=welcome()), \
                patch.object(tinder, 'adb_call') as call:
            with self.assertRaisesRegex(RuntimeError, 'House Rules screen'):
                tinder.agree_house_rules('test')
        call.assert_not_called()

    def test_explicit_agreement_action_taps_only_known_control(self):
        xml = '<hierarchy>' + ''.join('<node package="com.tinder" text="' + label + '"/>' for label in ('Welcome to Tinder.', 'Please follow these House Rules.', 'I agree')) + '</hierarchy>'
        with patch.object(tinder, 'read_ui', return_value=xml), \
                patch.object(tinder, 'button_center', return_value=(50, 150)), \
                patch.object(tinder, 'adb_call') as call:
            tinder.agree_house_rules('test')
        call.assert_called_once_with('test', 'shell', 'input', 'tap', '50', '150')

    def test_house_rules_are_recognized_only_for_tinder(self):
        xml = '<hierarchy>' + ''.join(
            '<node package="com.tinder" text="' + label + '"/>'
            for label in ('Welcome to Tinder.', 'Please follow these House Rules.', 'I agree')) + '</hierarchy>'
        self.assertEqual(tinder.classify(xml), 'house-rules')
        self.assertEqual(tinder.classify(xml.replace('com.tinder', 'other.app')), 'unknown')
        self.assertIn('I agree', tinder.sanitized_xml(xml))

    def test_invalid_auto_submission_is_recognized_without_retry(self):
        provider = Mock()
        provider.verification_code.return_value = '012345'
        rejected = otp().replace('</hierarchy>', '<node package="com.tinder" text="' + tinder.INVALID_CODE + '"/></hierarchy>')
        self.assertEqual(tinder.classify(rejected), 'verification-code-invalid')
        with patch.object(tinder, 'read_ui', side_effect=[otp(), rejected]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'button_center') as button:
            tinder.enter_code('test', provider)
        self.assertEqual(call.call_count, 1)
        button.assert_not_called()

    def test_code_preserves_leading_zero_and_uses_stdin(self):
        provider = Mock()
        provider.verification_code.return_value = '012345'
        with patch.object(tinder, 'read_ui', side_effect=[otp(), otp('012345')]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run') as run, \
                patch.object(tinder, 'button_center', return_value=(50, 150)):
            tinder.enter_code('test', provider)
        self.assertEqual(run.call_args.kwargs['input'], 'input text 012345\n')
        self.assertNotIn('012345', repr(run.call_args.args))
        self.assertNotIn('012345', repr(call.call_args_list))
        self.assertEqual(call.call_args.args, ('test', 'shell', 'input', 'tap', '50', '150'))
        self.assertNotIn('text="0"', tinder.sanitized_xml(otp('012345')))

    def test_code_mismatch_does_not_submit(self):
        provider = Mock()
        provider.verification_code.return_value = '012345'
        with patch.object(tinder, 'read_ui', side_effect=[otp(), otp('999999')]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'button_center') as button:
            with self.assertRaisesRegex(RuntimeError, 'read-back did not match'):
                tinder.enter_code('test', provider)
        self.assertEqual(call.call_count, 1)
        button.assert_not_called()

    def test_code_auto_transition_does_not_tap_next_screen(self):
        provider = Mock()
        provider.verification_code.return_value = '012345'
        with patch.object(tinder, 'read_ui', side_effect=[otp(), welcome()]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'button_center') as button:
            tinder.enter_code('test', provider)
        self.assertEqual(call.call_count, 1)
        button.assert_not_called()

    def test_phone_entry_uses_provider_stdin_and_does_not_submit(self):
        xml = ('<hierarchy><node package="com.tinder" text="Can we get your number?"/>'
               '<node package="com.tinder" text="US +1"/>'
               '<node package="com.tinder" class="android.widget.EditText" resource-id="com.tinder:id/phoneNumberInputView" text="Phone Number" bounds="[0,0][100,100]"/></hierarchy>')
        entered = xml.replace('text="Phone Number"', 'text="2025550123"')
        provider = Mock()
        provider.phone_number.return_value = '+12025550123'
        with patch.object(tinder, 'read_ui', side_effect=[xml, entered]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run') as run:
            tinder.enter_phone('test', provider)
        provider.phone_number.assert_called_once()
        provider.verification_code.assert_not_called()
        self.assertNotIn('2025550123', repr(run.call_args.args))
        self.assertIn('2025550123', run.call_args.kwargs['input'])
        self.assertNotIn('2025550123', repr(call.call_args_list))
        self.assertEqual(sum(c.args[1:4] == ('shell', 'input', 'tap') for c in call.call_args_list), 1)
        self.assertNotIn('2025550123', tinder.sanitized_xml(entered))
        self.assertEqual(tinder.classify(xml), 'phone-entry')

    def test_signup_phone_entry_submits_only_after_readback(self):
        xml = ('<hierarchy><node package="com.tinder" text="Can we get your number?"/>'
               '<node package="com.tinder" text="US +1"/>'
               '<node package="com.tinder" class="android.widget.EditText" resource-id="com.tinder:id/phoneNumberInputView" text="Phone Number" bounds="[0,0][100,100]"/>'
               '<node package="com.tinder" text="Next"/></hierarchy>')
        entered = xml.replace('text="Phone Number"', 'text="2025550123"')
        provider = Mock()
        provider.phone_number.return_value = '+12025550123'
        with patch.object(tinder, 'read_ui', side_effect=[xml, entered]), \
                patch.object(tinder, 'adb_call') as call, \
                patch.object(tinder.subprocess, 'run'), \
                patch.object(tinder, 'button_center', return_value=(50, 150)):
            tinder.enter_phone('test', provider, submit=True)
        self.assertEqual(call.call_args.args, ('test', 'shell', 'input', 'tap', '50', '150'))

    def test_google_number_hint_is_recognized_without_using_suggested_number(self):
        xml = '<hierarchy><node package="com.google.android.gms" text="Choose a phone number"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'google-number-hint')

    def test_only_observed_packages_and_markers_are_recognized(self):
        self.assertEqual(tinder.classify(welcome()), 'welcome-terms-and-login')
        self.assertEqual(tinder.classify(welcome().replace('com.tinder', 'another.app')), 'unknown')
        xml = '<hierarchy><node package="com.google.android.permissioncontroller" text="Allow Tinder to send you notifications?"/></hierarchy>'
        self.assertEqual(tinder.classify(xml), 'notification-permission')

    def test_fixture_drops_personal_values_and_unknown_attributes(self):
        xml = '<hierarchy><node package="com.tinder" class="android.widget.EditText" text="test@example.invalid" token="secret"/><node text="123456"/><node text="Continue with Phone Number"/></hierarchy>'
        safe = tinder.sanitized_xml(xml)
        for value in ('test@example.invalid', 'secret', '123456'):
            self.assertNotIn(value, safe)
        self.assertIn('Continue with Phone Number', safe)

    def test_welcome_observation_never_taps_or_restarts(self):
        def call(serial, *args):
            if args == ('shell', 'getprop ro.boot.qemu.avd_name'):
                return 'Test'
            if args == ('shell', 'pm', 'path', tinder.PACKAGE):
                return 'package:/data/app/tinder/base.apk'
            raise AssertionError('Unexpected mutation')
        with tempfile.TemporaryDirectory() as folder, patch.object(tinder, 'adb_call', side_effect=call), patch.object(tinder, 'read_ui', return_value=welcome()):
            self.assertEqual(tinder.observe('test', 'Test', folder), 2)


if __name__ == '__main__':
    unittest.main()
