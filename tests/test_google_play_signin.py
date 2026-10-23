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
