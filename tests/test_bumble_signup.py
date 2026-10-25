import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bumble_signup as b

UI_FIXTURES = ROOT / 'tests/fixtures/bumble-signup'


def screen(filename):
    return b.Screen((UI_FIXTURES / filename).read_text())


class BumbleTests(unittest.TestCase):
    def test_observed_captcha_and_image_error_pause_without_tapping(self):
        screens = [('<node text="Protecting your account"/><node text="Please solve this puzzle so we know you are a real person"/>', 'manual CAPTCHA'),
                   ('<node text="Something went wrong. Please reload the challenge to try again."/>', 'challenge loading error')]
        for xml, expected in screens:
            runner = self.runner()
            with patch.object(runner, 'manual') as manual, patch.object(runner, 'click') as click:
                state, action = runner.step(b.Screen('<hierarchy>' + xml + '</hierarchy>'))
                self.assertEqual(state, expected)
                action()
                manual.assert_called_once()
                click.assert_not_called()

    def test_account_block_is_a_terminal_non_action_state(self):
        runner = self.runner()
        state, action = runner.step(b.Screen(
            '<hierarchy><node text="Account blocked"/><node text="Community Guidelines"/></hierarchy>'))
        self.assertEqual(state, 'account blocked')
        self.assertEqual(action, 'account_blocked')

    def runner(self, **profile):
        return b.Signup('emulator-test', 'Test', Path('/tmp'), dict(verification=True, **profile))

    def test_initial_profile_reuses_creation_choices_without_asking_credentials(self):
        with patch.object(b, 'ask') as ask, patch.object(b, 'choose') as choose, \
                patch.object(b, 'random_photos', return_value=[Path(f'photo-{i}.jpg') for i in range(4)]):
            profile = b.collect_profile('Alex', 'Nonbinary')
        ask.assert_not_called()
        choose.assert_not_called()
        self.assertEqual(profile['name'], 'Alex')
        self.assertEqual(profile['gender'], 'Nonbinary')
        self.assertEqual(len(set(profile['photos'])), 4)
        self.assertNotIn('phone', profile)
        self.assertTrue(profile['verification'])
        self.assertEqual(profile['country'], 'United States')
        self.assertNotIn('birthday', profile)
        self.assertNotIn('show_gender', profile)
        self.assertEqual(profile['email'], '')
        self.assertNotIn('intention', profile)

    def test_saved_choices_skip_screen_questions_and_still_ask_for_fresh_phone(self):
        runner = self.runner(**{k: v for k, v in b.profile_defaults().items() if k != 'verification'})
        runner.profile['name'] = 'Alex'
        with patch.object(b, 'ask', return_value='3035550123') as ask, patch.object(b, 'choose') as choose, \
                patch.object(runner, 'fill'), patch.object(runner, 'click') as click, \
                patch.object(runner, 'select_continue') as select:
            runner.phone_details()
            runner.intro()
            runner.email()
            runner.dating_intention()
        self.assertEqual(ask.call_count, 1)
        self.assertIn('National phone number', ask.call_args.args[0])
        choose.assert_not_called()
        self.assertIn(('Skip',), [c.args for c in click.call_args_list])
        self.assertEqual(select.call_count, 1)
        self.assertIn(select.call_args.args[0], ['A long-term relationship', 'A life partner',
                      'Open to seeing where things go', 'Something casual', 'Marriage',
                      'Ethical non-monogamy'])

    def test_phone_number_prompt_waits_for_phone_screen_action_and_is_cached(self):
        runner = self.runner()
        with patch.object(b, 'ask', return_value='(303) 555-0123') as ask, \
                patch.object(runner, 'click') as click, patch.object(runner, 'fill') as fill:
            # Recognizing other screens and phone entry itself never prompts.
            runner.step(screen('46-verification-result.xml'))
            state, action = runner.step(screen('40-new-phone.xml'))
            ask.assert_not_called()
            self.assertEqual(state, 'phone number')
            action()
            self.assertEqual(ask.call_count, 1)
            self.assertEqual(runner.profile['phone'], '3035550123')
            self.assertTrue(ask.call_args.kwargs['secret'])
            fill.assert_called_once_with(0, '3035550123')
            click.assert_called_once_with('Continue')
            runner.phone_details()
            self.assertEqual(ask.call_count, 1)

    def test_random_photo_pool_uses_four_distinct_images_and_excludes_video(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for i in range(8):
                (directory / f'{i}.jpeg').write_bytes(b'image')
            (directory / 'excluded.mp4').write_bytes(b'video')
            (directory / 'notes.txt').write_text('not a photo')
            photos = b.random_photos(directory)
            self.assertEqual(len(photos), 4)
            self.assertEqual(len(set(photos)), 4)
            self.assertTrue(all(p.suffix == '.jpeg' for p in photos))

    def test_photo_pool_fails_if_fewer_than_four_images(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'four images'):
                b.random_photos(directory)

    def test_prompt_pool_covers_every_mapped_question_with_three_answers(self):
        pool = b.prompt_pool()
        catalog = json.loads((ROOT / 'bumble-signup/prompt-picker/catalog.json').read_text())
        self.assertEqual(len(catalog), 52)
        self.assertEqual(len(pool), 156)
        self.assertEqual(len({(p['question'], p['answer']) for p in pool}), 156)
        for entry in catalog:
            self.assertEqual(sum(p['question'] == entry['question'] and p['category'] == entry['category'] for p in pool), 3)
        self.assertTrue(all(p['answer'].isascii() and 1 <= len(p['answer']) <= 160 for p in pool))
        selected = b.random_prompts()
        self.assertEqual(len(selected), 2)
        self.assertNotEqual(selected[0]['question'], selected[1]['question'])
        self.assertTrue(all(p in pool for p in selected))
        excluded = selected[0]['question']
        self.assertTrue(all(p['question'] != excluded for p in b.random_prompts(exclude={excluded})))

    def test_choose_prompt_switches_category_and_scrolls_question_list(self):
        runner = self.runner()
        runner.active_prompt = next(p for p in b.prompt_pool() if p['question'] == 'When my phone dies I')
        date = b.Screen((UI_FIXTURES / 'prompt-picker/00-00.xml').read_text())
        bit = b.Screen((UI_FIXTURES / 'prompt-picker/04-00.xml').read_text())
        bottom = b.Screen((UI_FIXTURES / 'prompt-picker/04-01.xml').read_text())
        with patch.object(runner, 'read', side_effect=[date, date, bit, bit, bit, bit, bit, bottom]), \
                patch.object(runner, 'swipe_prompt_picker') as swipe, patch.object(runner, 'tap') as tap:
            runner.choose_prompt()
        self.assertEqual(tap.call_args_list[0].args[0].get('text'), 'Bit of fun')
        self.assertEqual(tap.call_args_list[-1].args[0].get('text'), 'When my phone dies I')
        self.assertTrue(any(c.kwargs.get('horizontal') for c in swipe.call_args_list))
        self.assertTrue(any(not c.kwargs for c in swipe.call_args_list))

    def test_prompt_swipes_keep_vertical_motion_below_category_strip(self):
        runner = self.runner()
        current = b.Screen((UI_FIXTURES / 'prompt-picker/00-00.xml').read_text())
        with patch.object(runner, 'call') as call, patch.object(b.time, 'sleep'):
            runner.swipe_prompt_picker(current)
            vertical = call.call_args.args
            runner.swipe_prompt_picker(current, horizontal=True)
            horizontal = call.call_args.args
            with self.assertRaises(b.UIActionError):
                runner.swipe_prompt_picker(screen('46-verification-result.xml'))
        self.assertEqual(vertical[3], vertical[5])
        self.assertGreater(int(vertical[4]), int(vertical[6]))
        self.assertGreater(int(vertical[6]), 320)
        self.assertEqual(horizontal[4], horizontal[6])

    def test_one_saved_prompt_adds_second_and_two_saved_prompts_allow_continue(self):
        runner = self.runner()
        self.assertEqual(runner.step(screen('78-prompt-saved.xml'))[0], 'profile prompt 2')
        self.assertNotEqual(runner.active_prompt['question'], 'Give me travel tips for')
        xml = (UI_FIXTURES / '74-next.xml').read_text()
        xml = xml.replace('text="First prompt"', 'text="Give me travel tips for"')
        xml = xml.replace('text="Second prompt"', 'text="Would you rather"')
        self.assertEqual(runner.step(b.Screen(xml))[0], 'two prompts saved')

    def test_selected_interest_is_read_from_parent_checkbox(self):
        selected = screen('67-interests.xml')
        self.assertTrue(selected.checked('Coffee'))
        self.assertTrue(selected.checked('Crafts'))
        self.assertFalse(selected.checked('Cats'))

    def test_native_profile_and_verification_status_match_live_ui(self):
        live = UI_FIXTURES / 'live-20261022'
        runner = self.runner()
        self.assertEqual(runner.step(b.Screen((live / '41-profile.xml').read_text()))[0], 'profile')
        editor = b.Screen((live / '42-profile-editor.xml').read_text())
        self.assertIsNone(editor.find('Verification'))
        with patch.object(runner, 'read', return_value=editor), patch.object(runner, 'tap') as tap:
            runner.open_verification()
        self.assertEqual(tap.call_args.args[0].get('content-desc'), 'Not ID verified')

    def test_live_native_interest_picker_exposes_activity_labels(self):
        live = b.Screen((UI_FIXTURES / 'live-20261022/44-interest-picker.xml').read_text())
        labels = live.interest_labels()
        self.assertIn('Cold plunging', labels)
        self.assertIn('Boxing', labels)
        self.assertNotIn('Sports', labels)
        self.assertNotIn('Continue', labels)
        self.assertGreaterEqual(len(labels), 5)

    def test_persistent_feed_error_uses_profile_after_one_restart(self):
        runner = self.runner()
        runner.restarted = True
        self.assertEqual(runner.step(screen('92-location-enabled.xml'))[0], 'profile tab after feed error')

    def test_random_interest_selection_samples_five_and_requires_confirmation(self):
        runner = self.runner()
        initial = screen('66-next.xml')
        confirmed = b.Screen((UI_FIXTURES / '66-next.xml').read_text().replace('0/5 selected', '5/5 selected'))
        clicks = []
        def read():
            # All five selections must be sent before Continue is allowed.
            return confirmed if len(clicks) == 5 else initial
        def click(label):
            if label == 'Continue':
                self.assertEqual(len(clicks), 5)
            else:
                clicks.append(label)
        with patch.object(runner, 'read', side_effect=read), patch.object(runner, 'click', side_effect=click):
            runner.interests()
        self.assertEqual(len(set(clicks)), 5)
        self.assertEqual(set(clicks), set(runner.profile['interests']))

    def test_optional_profile_details_choose_visible_answers_instead_of_skip(self):
        fixtures = {
            'Your height': '64-next.xml',
            'Let’s talk about your lifestyle': '68-next.xml',
            'Do you have kids or family plans?': '70-next.xml',
            'What’s important in your life?': '72-next.xml',
        }
        for title, filename in fixtures.items():
            with self.subTest(title=title):
                runner = self.runner()
                current = screen(filename)
                with patch.object(runner, 'read', return_value=current), \
                        patch.object(runner, 'click') as click, \
                        patch.object(b.secrets, 'choice', side_effect=lambda values: values[0]):
                    state, action = runner.step(current)
                    self.assertEqual(state, title)
                    action()
                self.assertNotIn(('Skip',), [call.args for call in click.call_args_list])
                self.assertEqual(click.call_args_list[-1].args, ('Continue',))
                self.assertTrue(runner.profile['profile_details'][title])

    def test_random_height_accepts_us_imperial_labels(self):
        runner = self.runner()
        current = b.Screen('<hierarchy><node text="Your height" enabled="true" bounds="[0,0][10,10]"/>'
                           '<node text="5\' 4\'\'" enabled="true" bounds="[0,20][100,40]"/>'
                           '<node content-desc="Continue" enabled="true" bounds="[0,50][100,70]"/></hierarchy>')
        with patch.object(runner, 'read', return_value=current), patch.object(runner, 'click') as click:
            runner.random_profile_details('Your height')
        self.assertEqual(click.call_args_list[0].args, ("5' 4''",))
        self.assertEqual(click.call_args_list[-1].args, ('Continue',))

    def test_ethnicity_and_visibility_are_randomized(self):
        current = b.Screen('<hierarchy><node text="What’s your ethnicity?" enabled="true" bounds="[0,0][100,20]"/>'
                           '<node text="European" enabled="true" bounds="[0,30][100,50]"/>'
                           '<node class="android.widget.Switch" resource-id="com.bumble.app:id/ethnicity_selection_show_profile_toggle" '
                           'enabled="true" checkable="true" checked="false" bounds="[0,60][100,80]"/>'
                           '<node content-desc="Continue" enabled="true" bounds="[0,90][100,110]"/></hierarchy>')
        runner = self.runner()
        with patch.object(runner, 'read', return_value=current), patch.object(runner, 'click') as click, \
                patch.object(runner, 'tap') as tap, \
                patch.object(b.secrets, 'choice', side_effect=['European', True]):
            state, action = runner.step(current)
            self.assertEqual(state, 'random ethnicity')
            action()
        self.assertEqual(click.call_args_list[0].args, ('European',))
        self.assertEqual(click.call_args_list[-1].args, ('Continue',))
        tap.assert_called_once()
        self.assertEqual(runner.profile['ethnicity'], 'European')
        self.assertTrue(runner.profile['show_ethnicity'])

    def test_recorded_signup_screens_and_verification_navigation(self):
        # Saved app evidence, including loading overlays and the final manual
        # selfie handoff. No device or account is touched by these tests.
        expected = {
            '03-phone-entry.xml': 'phone number', '21-country.xml': 'country selection',
            '40-new-phone.xml': 'phone number', '41-new-confirm.xml': 'confirm phone number',
            '42-new-request.xml': 'loading', '43-code-entry.xml': 'SMS code',
            '44-code-result.xml': 'SMS code', '45-after-code.xml': 'loading',
            '46-verification-result.xml': 'optional passkey', '47-profile-start.xml': 'location',
            '48-after-location.xml': 'notifications', '49-profile.xml': 'name and birthday',
            '51-intro-filled.xml': 'name and birthday', '52-after-intro.xml': 'confirm age',
            '53-gender.xml': 'gender', '54-woman-selected.xml': 'gender',
            '55-next.xml': 'gender visibility', '56-next.xml': 'recovery email',
            '57-email-filled.xml': 'recovery email', '58-after-email.xml': 'loading',
            '59-next.xml': 'marketing', '60-next.xml': 'dating preference',
            '61-dating-selection.xml': 'dating preference', '62-next.xml': 'dating intention',
            '64-next.xml': 'Your height', '66-next.xml': 'random interests',
            '68-next.xml': 'Let’s talk about your lifestyle', '70-next.xml': 'Do you have kids or family plans?',
            '72-next.xml': 'What’s important in your life?', '74-next.xml': 'profile prompt 1',
            '75-prompts.xml': 'choose prompt 1', '76-prompt-answer.xml': 'prompt answer 1',
            '78-prompt-saved.xml': 'profile prompt 2', '79-next.xml': 'profile photos',
            '80-photo-source.xml': 'photo source', '82-photo-picker.xml': 'photo picker',
            '85-photo-upload.xml': 'photo picker', '86-photo-current.xml': 'photo crop',
            '87-upload-result.xml': 'loading', '88-photo-status.xml': 'photos uploaded',
            '89-after-photos.xml': 'community guidelines', '91-current.xml': 'location permission',
            '92-location-enabled.xml': 'app restart', '96-final-state.xml': 'match notice',
            '97-main.xml': 'optional ethnicity', '98-main.xml': 'open profile navigation',
            '99-current.xml': 'profile tab', '100-profile.xml': 'profile',
            '101-complete-profile.xml': 'profile editor', '102-verification-menu.xml': 'verification menu',
            '103-photo-verification.xml': 'photo verification',
            '104-verification-instructions.xml': 'selfie introduction',
            '105-verification-next.xml': 'selfie instructions',
        }
        runner = self.runner()
        for filename, state in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(runner.step(screen(filename))[0], state)
        self.assertEqual(runner.step(screen('105-verification-next.xml'))[1], 'verification_ready')
        runner.profile['verification'] = False
        self.assertEqual(runner.step(screen('98-main.xml'))[1], 'signup_complete')

    def test_verification_button_uses_footer_instead_of_title(self):
        node = screen('104-verification-instructions.xml').find('Get verified')
        self.assertGreater(b.center(node)[1], 2000)
        self.assertIsNone(screen('43-code-entry.xml').find('Continue'))

    def test_gender_visibility_uses_switch_not_gender_checkbox(self):
        runner = self.runner(show_gender=False)
        with patch.object(runner, 'read', return_value=screen('55-next.xml')), \
                patch.object(runner, 'call') as call, patch.object(runner, 'click'):
            runner.gender_visibility()
        self.assertEqual(call.call_args.args, ('shell', 'input', 'tap', '955', '908'))

    def test_user_text_is_humanized_and_stays_out_of_process_arguments(self):
        runner = self.runner()
        class FixedRandom:
            def uniform(self, low, high):
                return (low + high) / 2
            def random(self):
                return 1.0
        completed = subprocess.CompletedProcess(['adb'], 0, '', '')
        with patch.object(b.secrets, 'SystemRandom', return_value=FixedRandom()), \
                patch.object(b.subprocess, 'run', return_value=completed) as run, \
                patch.object(b.time, 'sleep') as sleep:
            runner.type_text('A b')
            self.assertEqual([call.kwargs['input'] for call in run.call_args_list],
                             ['input text A\n', 'input text %s\n', 'input text b\n'])
            self.assertTrue(all(call.args[0] == ['adb', '-s', 'emulator-test', 'shell']
                                for call in run.call_args_list))
            self.assertEqual(sleep.call_count, 2)
            self.assertTrue(all(0.045 <= call.args[0] <= 0.565 for call in sleep.call_args_list))
            with self.assertRaises(RuntimeError):
                runner.type_text('café')

    def test_sms_not_resent_when_code_screen_persists(self):
        runner = self.runner()
        pending = screen('43-code-entry.xml')
        final = screen('105-verification-next.xml')
        with patch.object(runner, 'call', side_effect=['package:/app/base.apk', 'Test\nOK']), \
                patch.object(b, 'ensure_network'), \
                patch.object(runner, 'verify_permissions'), \
                patch.object(runner, 'launch'), patch.object(runner, 'read', side_effect=[pending, pending, final]), \
                patch.object(runner, 'sms') as sms, patch.object(b.time, 'sleep'):
            self.assertEqual(runner.run(), 'verification_ready')
            self.assertEqual(sms.call_count, 1)

    def test_completion_requires_both_location_and_notification_grants(self):
        runner = self.runner()
        grants = '\n'.join('android.permission.' + permission + ': granted=true, flags=[]'
                           for permission in ['ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION', 'POST_NOTIFICATIONS'])
        with patch.object(runner, 'call', return_value=grants):
            runner.verify_permissions()
        with patch.object(runner, 'call', return_value=grants.replace('POST_NOTIFICATIONS: granted=true',
                                                                   'POST_NOTIFICATIONS: granted=false')):
            with self.assertRaises(b.UIActionError):
                runner.verify_permissions()

    def test_continue_dismisses_keyboard_before_reading_button_bounds(self):
        runner = self.runner()
        events = []
        def call(*args):
            events.append(args)
            return 'mInputShown=true' if args[-1] == 'input_method' else ''
        def read():
            events.append(('read_ui',))
            return b.Screen('<hierarchy><node text="Continue" enabled="true" bounds="[0,100][100,200]"/></hierarchy>')
        with patch.object(runner, 'call', side_effect=call), patch.object(runner, 'read', side_effect=read):
            runner.click('Continue')
        self.assertEqual(events, [('shell', 'dumpsys', 'input_method'),
                                  ('shell', 'input', 'keyevent', 'KEYCODE_BACK'), ('read_ui',),
                                  ('shell', 'input', 'tap', '50', '150')])

    def test_prompt_save_taps_footer_without_dismissing_keyboard(self):
        runner = self.runner()
        current = b.Screen('<hierarchy><node content-desc="Double tap to save your answer" '
                           'enabled="true" bounds="[0,100][100,200]"/></hierarchy>')
        with patch.object(runner, 'read', return_value=current), patch.object(runner, 'call') as call:
            runner.click('Double tap to save your answer')
        call.assert_called_once_with('shell', 'input', 'tap', '50', '150')

    def test_dating_preference_is_random_for_every_profile_gender(self):
        for gender in ('Woman', 'Man', 'Nonbinary'):
            runner = self.runner(gender=gender)
            with patch.object(b.secrets, 'choice', side_effect=lambda values: values[-1]), \
                    patch.object(runner, 'select_continue') as select:
                runner.dating_preference()
            select.assert_called_once_with('Nonbinary people')

    def test_random_birthday_is_an_adult_between_21_and_35(self):
        today = b.dt.date(2026, 10, 24)
        birthday = b.random_adult_birthday(today)
        age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
        self.assertGreaterEqual(age, 21)
        self.assertLessEqual(age, 35)

    def test_sms_supports_current_container_only_hierarchy_and_mac_clipboard(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        self.assertIsNone(current.find(rid='pinItem_textView'))
        with patch.object(runner, 'read', side_effect=[current, screen('46-verification-result.xml')]), \
                patch.object(b, 'ask', return_value='/mac'), \
                patch.object(b.subprocess, 'run', return_value=subprocess.CompletedProcess(['pbpaste'], 0, '123456\n')) as run, \
                patch.object(runner, 'type_text') as type_text, patch.object(runner, 'call') as call:
            runner.sms()
        run.assert_called_once_with(['pbpaste'], capture_output=True, text=True, check=True, timeout=5)
        type_text.assert_called_once_with('123456')
        call.assert_called_once_with('shell', 'input', 'tap', '111', '664')

    def test_enter_pastes_guest_clipboard_without_reading_mac_clipboard(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        with patch.object(runner, 'read', side_effect=[current, screen('46-verification-result.xml')]), \
                patch.object(b, 'ask', return_value=''), patch.object(b.subprocess, 'run') as run, \
                patch.object(runner, 'call') as call:
            runner.sms()
        run.assert_not_called()
        self.assertIn(('shell', 'input', 'keyevent', 'KEYCODE_PASTE'), [c.args for c in call.call_args_list])

    def test_sms_checks_for_input_before_requesting_code(self):
        runner = self.runner()
        with patch.object(runner, 'read', return_value=b.Screen('<hierarchy/>')), patch.object(b, 'ask') as ask:
            with self.assertRaises(b.UIActionError):
                runner.sms()
        ask.assert_not_called()

    def test_sms_falls_back_to_saved_arrow_when_footer_stays_disabled(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        with patch.object(runner, 'read', return_value=current), patch.object(b, 'ask', return_value='123456') as ask, \
                patch.object(runner, 'type_text') as type_text, patch.object(runner, 'call') as call, \
                patch.object(b.time, 'sleep'):
            runner.sms()
            runner.sms()
        self.assertEqual(ask.call_count, 1)
        type_text.assert_called_once_with('123456')
        self.assertEqual(call.call_args_list[-1].args, ('shell', 'input', 'tap', '976', '1476'))
        self.assertEqual(sum(c.args == ('shell', 'input', 'tap', '976', '1476') for c in call.call_args_list), 2)

    def test_sms_fallback_survives_ui_dump_failure_after_code_is_entered(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        with patch.object(runner, 'read', side_effect=[current, subprocess.TimeoutExpired('adb', 12)]), \
                patch.object(b, 'ask', return_value='123456'), patch.object(runner, 'type_text'), \
                patch.object(runner, 'call') as call:
            runner.sms()
        self.assertEqual(call.call_args.args, ('shell', 'input', 'tap', '976', '1476'))

    def test_sms_never_uses_saved_arrow_after_navigation_away(self):
        runner = self.runner()
        runner.sms_code_entered = True
        runner.sms_arrow = (976, 1476)
        with patch.object(runner, 'read', return_value=screen('46-verification-result.xml')), \
                patch.object(runner, 'call') as call, patch.object(b, 'ask') as ask:
            runner.sms()
        call.assert_not_called()
        ask.assert_not_called()
        self.assertFalse(runner.sms_code_entered)

    def test_sms_already_filled_submits_without_asking_or_reentering_code(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        footer = next(n for n in current.nodes if n.get('resource-id', '').endswith(':id/reg_footer_button'))
        footer.set('enabled', 'true')
        footer.set('clickable', 'true')
        with patch.object(runner, 'read', return_value=current), patch.object(b, 'ask') as ask, \
                patch.object(runner, 'type_text') as type_text, patch.object(runner, 'tap') as tap:
            runner.sms()
        ask.assert_not_called()
        type_text.assert_not_called()
        tap.assert_called_once_with(footer)

    def test_sms_waits_for_continue_to_enable_after_entry(self):
        runner = self.runner()
        current = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        ready = b.Screen((ROOT / 'fixtures/bumble-sms-container.xml').read_text())
        footer = next(n for n in ready.nodes if n.get('resource-id', '').endswith(':id/reg_footer_button'))
        footer.set('enabled', 'true')
        footer.set('clickable', 'true')
        with patch.object(runner, 'read', side_effect=[current, current, ready]), \
                patch.object(b, 'ask', return_value='123456') as ask, patch.object(runner, 'call'), \
                patch.object(runner, 'type_text') as type_text, patch.object(runner, 'tap') as tap, \
                patch.object(b.time, 'sleep'):
            runner.sms()
        self.assertEqual(ask.call_count, 1)
        type_text.assert_called_once_with('123456')
        tap.assert_called_once_with(footer)

    def test_error_capture_uses_only_emulator_window_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner()
            runner.output = Path(directory)
            def capture(command, **kwargs):
                target = Path(command[-1])
                target.parent.mkdir(parents=True)
                target.touch()
                return subprocess.CompletedProcess(command, 0)
            with patch.object(b.subprocess, 'run', side_effect=capture) as run:
                path = runner.capture_window()
            self.assertTrue(path.is_file())
            self.assertEqual(run.call_args.args[0][:3], ['bash', str(ROOT / 'capture_emulator_window.sh'), 'Test'])

    def test_picker_never_guesses_when_library_count_differs(self):
        runner = self.runner(photos=['one', 'two', 'three', 'four', 'five'])
        runner.staged_paths = {'/storage/emulated/0/Pictures/Signup/new.jpg'}
        with patch.object(runner, 'read', return_value=screen('82-photo-picker.xml')), \
                patch.object(runner, 'call', return_value='Row: 0 _data=/storage/emulated/0/Pictures/Signup/new.jpg') as call:
            with self.assertRaises(RuntimeError):
                runner.photo_picker()
            self.assertEqual(call.call_count, 1)  # Media query only; no taps.

    def test_picker_rejects_same_count_of_unrelated_photos(self):
        runner = self.runner(photos=['one', 'two', 'three', 'four'])
        runner.staged_paths = {'/storage/emulated/0/Pictures/Signup/new.jpg'}
        with patch.object(runner, 'read', return_value=screen('82-photo-picker.xml')), \
                patch.object(runner, 'call', return_value='Row: 0 _data=/storage/emulated/0/DCIM/old.jpg') as call:
            with self.assertRaises(RuntimeError):
                runner.photo_picker()
            self.assertEqual(call.call_count, 1)

    def test_nonterminal_saves_pending_status_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'bumble_signup.py'),
                                     '--serial', 'unused', '--avd', 'unused', '--output', directory],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            status = json.loads((Path(directory) / 'status.json').read_text())
            self.assertEqual(status['status'], 'awaiting_terminal')
            self.assertEqual(set(status), {'status', 'elapsed_seconds'})


if __name__ == '__main__':
    unittest.main()
