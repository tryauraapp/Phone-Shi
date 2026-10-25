import io
from pathlib import Path
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import google_play_signin as google
from play_store_install import button_center


def account_screen(password=False, heading='Sign in - Google Accounts', forgot=True):
    return ('<hierarchy>'
            f'<node text="{heading}"/>'
            + ('<node text="Forgot email?"/>' if forgot else '')
            + f'<node class="android.widget.EditText" password="{str(password).lower()}" bounds="[0,0][100,100]"/>'
            '<node text="Next" clickable="true" enabled="true" bounds="[100,100][200,200]"/>'
            '</hierarchy>')


class GooglePlaySignInTests(unittest.TestCase):
    def test_account_protection_puzzle_requires_manual_completion(self):
        xml = '<hierarchy><node text="Protecting your account"/><node text="Please solve this puzzle so we know you are a real person"/><node text="Start Puzzle"/></hierarchy>'
        self.assertEqual(google.sign_in_action(xml), 'captcha')

    def test_store_welcome_get_started_is_recognized(self):
        xml = '<hierarchy><node text="Welcome to Google Play"/><node text="Get started"/></hierarchy>'
        self.assertEqual(google.sign_in_action(xml), 'store-welcome')

    def test_optional_store_recommendations_are_recognized(self):
        xml = '<hierarchy><node text="What are you into?"/><node text="Choose apps categories"/><node text="Skip"/></hierarchy>'
        self.assertEqual(google.sign_in_action(xml), 'store-recommendations')

    def test_optional_payment_setup_is_recognized(self):
        xml = ('<hierarchy>'
               '<node package="com.android.vending" text="Complete account setup"/>'
               '<node package="com.android.vending" text="Add a payment option to complete your account. You won&apos;t be charged unless you make a purchase."/>'
               '<node package="com.android.vending" text="Skip" clickable="true" enabled="true" bounds="[0,0][100,100]"/>'
               '</hierarchy>')
        self.assertEqual(google.play_screen_action(xml), 'payment-setup')

    def test_observed_overlays_take_priority_over_background_listing(self):
        for filename, action in [('complete-account-setup.xml', 'account-setup'),
                                 ('play-pass-offer.xml', 'play-pass'),
                                 ('google-terms.xml', 'agreement')]:
            xml = (Path(__file__).parent / 'fixtures/google-play' / filename).read_text()
            self.assertEqual(google.sign_in_action(xml), action)

    def test_terms_tap_agree_after_explicit_workflow_authorization(self):
        xml = (Path(__file__).parent / 'fixtures/google-play/google-terms.xml').read_text()
        done = '<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/></hierarchy>'
        with patch.object(google.sys.stdin, 'isatty', return_value=True), \
                patch.object(google, 'read_ui', side_effect=[xml, done]), \
                patch.object(google.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
                patch.object(google.time, 'sleep'):
            google.ensure_sign_in('test', button_center)
        x, y = button_center(xml, 'I agree')
        self.assertEqual(run.call_args.args[0],
                         ['adb', '-s', 'test', 'shell', 'input', 'tap', str(x), str(y)])

    def test_phone_signin_can_finish_while_private_terminal_prompt_waits(self):
        done = '<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/></hierarchy>'
        with patch.object(google.sys.stdin, 'isatty', return_value=True), \
                patch.object(google.getpass, 'getpass', return_value=''), \
                patch.object(google, 'read_ui', side_effect=[account_screen(), done, done]), \
                patch.object(google.subprocess, 'run') as run, \
                patch.object(google.time, 'sleep'):
            google.ensure_sign_in('test', button_center)
        run.assert_not_called()

    def test_observed_carrier_discovery_screen_is_skipped(self):
        fixture = Path(__file__).parent / 'fixtures/google-play/sign-in-with-ease.xml'
        xml = fixture.read_text()
        self.assertEqual(google.sign_in_action(xml), 'carrier-discovery')
        self.assertIsNotNone(button_center(xml, 'SKIP'))

    def test_observed_rooted_email_screen_with_uppercase_next(self):
        fixture = Path(__file__).parent / 'fixtures/google-play/rooted-email-entry.xml'
        xml = fixture.read_text()
        self.assertEqual(google.sign_in_action(xml), 'email')
        self.assertIsNotNone(button_center(xml, 'NEXT'))

    def test_signed_in_store_home_is_recognized_without_tapping_suggested_apps(self):
        xml = ('<hierarchy><node package="com.android.vending" '
               'content-desc="Signed in as Test test@example.invalid Account and settings."/>'
               '<node text="Install"/></hierarchy>')
        self.assertEqual(google.sign_in_action(xml), 'store-home')

    def test_requested_non_bumble_listing_is_done(self):
        xml = '<hierarchy><node text="Plenty of Fish: Dating"/></hierarchy>'
        self.assertEqual(google.sign_in_action(xml, 'Plenty of Fish'), 'done')

    def test_observed_email_and_password_screens(self):
        self.assertEqual(google.sign_in_action(account_screen()), 'email')
        self.assertEqual(google.sign_in_action(account_screen(password=True, forgot=False)), 'password')

    def test_security_verification_is_manual_even_with_password_field(self):
        self.assertEqual(google.sign_in_action(account_screen(password=True, heading='2-Step Verification')), 'manual')

    def test_optional_recovery_form_does_not_request_login_credentials(self):
        self.assertEqual(google.sign_in_action(account_screen(heading='Make sure you can always sign in')), 'recovery')

    def test_credentials_use_stdin_and_never_appear_in_host_arguments_or_output(self):
        email = 'test@example.invalid'
        password = 'example/secret!'
        email_xml = (Path(__file__).parent / 'fixtures/google-play/rooted-email-entry.xml').read_text()
        password_xml = account_screen(password=True, forgot=False)
        done = '<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/></hierarchy>'
        commands = []
        payloads = []

        def run(command, **kwargs):
            commands.append(command)
            if 'input' in kwargs:
                payloads.append(kwargs['input'])
            return subprocess.CompletedProcess(command, 0, '', '')

        output = io.StringIO()
        with patch.object(google.sys.stdin, 'isatty', return_value=True), \
                patch.object(google.getpass, 'getpass', side_effect=[email, password]), \
                patch.object(google, 'read_ui', side_effect=[email_xml, email_xml, password_xml, password_xml, done]), \
                patch.object(google.subprocess, 'run', side_effect=run), \
                patch.object(google.time, 'sleep'), redirect_stdout(output):
            google.ensure_sign_in('emulator-test', button_center)
        self.assertEqual(len(payloads), 2)
        self.assertIn(email, payloads[0])
        self.assertIn(password, payloads[1])
        for secret in (email, password):
            self.assertNotIn(secret, repr(commands))
            self.assertNotIn(secret, output.getvalue())

    def test_carrier_discovery_taps_skip_without_requesting_credentials(self):
        fixture = Path(__file__).parent / 'fixtures/google-play/sign-in-with-ease.xml'
        xml = fixture.read_text()
        done = '<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/></hierarchy>'
        with patch.object(google.sys.stdin, 'isatty', return_value=True), \
                patch.object(google.getpass, 'getpass') as prompt, \
                patch.object(google, 'read_ui', side_effect=[xml, done]), \
                patch.object(google.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
                patch.object(google.time, 'sleep'):
            google.ensure_sign_in('emulator-test', button_center)
        prompt.assert_not_called()
        x, y = button_center(xml, 'SKIP')
        self.assertEqual(run.call_args.args[0], ['adb', '-s', 'emulator-test', 'shell', 'input', 'tap', str(x), str(y)])


if __name__ == '__main__':
    unittest.main()
