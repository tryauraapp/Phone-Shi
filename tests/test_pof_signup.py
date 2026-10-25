import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pof_signup as pof


def node(text='', package=pof.PACKAGE, **attrs):
    values = {'package': package, 'text': text}
    values.update({key.replace('_', '-'): value for key, value in attrs.items()})
    return '<node ' + ' '.join(f'{key}="{value}"' for key, value in values.items()) + '/>'


def screen(*nodes):
    return '<hierarchy>' + ''.join(nodes) + '</hierarchy>'


class PofSignupTests(unittest.TestCase):
    def test_accidental_google_voice_input_uses_back_only_for_exact_active_ime(self):
        active = f'mCurMethodId={pof.VOICE_IME_ID}\nmInputShown=true\n'
        calls = []
        with patch.object(pof, 'adb_call', side_effect=lambda *args: calls.append(args) or active), \
                patch.object(pof.time, 'sleep'):
            self.assertTrue(pof.dismiss_accidental_voice_input('serial'))
        self.assertEqual(calls, [
            ('serial', 'shell', 'dumpsys', 'input_method'),
            ('serial', 'shell', 'input', 'keyevent', 'KEYCODE_BACK'),
        ])
        with patch.object(pof, 'adb_call', return_value=active.replace(pof.VOICE_IME_ID, 'other.IME')) as call:
            self.assertFalse(pof.dismiss_accidental_voice_input('serial'))
        call.assert_called_once_with('serial', 'shell', 'dumpsys', 'input_method')

    def test_classifies_observed_manual_boundaries(self):
        cases = {
            'credentials-and-terms-manual-stop': screen(
                node('Email address'), node('Password'), node('Terms of Service')),
            'phone-entry-manual-stop': screen(node('Verify your phone number'), node('Phone number')),
            'verification-code-manual-stop': screen(node('Enter verification code'), node('Resend code')),
            'photo-manual-stop': screen(node('Show those pearly whites.'),
                                        node('Time to share that lovely face with the world.')),
            'photo-source-manual-stop': screen(node('Remember...'), node('Add photo'),
                                               node('Take photo')),
            'photo-crop-manual-stop': screen(node('Upload'), node('Rotate')),
            'optional-selfie-verification-manual-stop': screen(
                node('Get Selfie-verified'), node('Get verified'), node('Skip')),
            'pledge-manual-stop': screen(node('The Pledge'), node('Be real.'), node('Got it')),
            'human-verification-manual-stop': screen(node('Complete face verification')),
        }
        for expected, xml in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(pof.classify(xml), expected)

    def test_classifies_permissions_and_profile_screens(self):
        permission = 'com.android.permissioncontroller'
        cases = {
            'notification-permission': screen(node('Allow POF to send you notifications?', permission),
                                              node('Allow', permission)),
            'location-permission': screen(node("Allow POF to access this device's location?", permission),
                                          node('While using the app', permission)),
            'welcome': screen(node('Create account'), node('Already a member? Log in')),
            'first-name': screen(node("What's your first name?")),
            'gender': screen(node('Woman'), node('Man'), node('Show my gender on my profile')),
            'location-details': screen(node('Country'), node('Postal code')),
            'birthday': screen(node('When is your birthday?')),
            'interests': screen(node('Interests')),
            'prestige-upsell': screen(node('Double your Chances with POF Prestige'),
                                      node('Continue as free')),
            'first-run-filters-tip': screen(node('Age and distance filters are here!'),
                                             node('Maybe later')),
            'main-feed-complete': screen(
                node('', resource_id=pof.PACKAGE + ':id/bottom_navigation'),
                node('', resource_id=pof.PACKAGE + ':id/home_navigation_meet_me'),
                node('', resource_id=pof.PACKAGE + ':id/meet_me_card_stack_view')),
        }
        for expected, xml in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(pof.classify(xml), expected)
        self.assertEqual(pof.classify(screen(node('Create account'), node('Sign in'))), 'welcome')
        self.assertEqual(pof.classify(screen(node('Let’s get started.'), node('First name'),
                                             node('What can we call you?'), node('Let’s go'))),
                         'first-name')
        self.assertEqual(pof.classify(screen(
            node('Bella', resource_id=pof.PACKAGE + ':id/first_name'),
            node('Let’s go', resource_id=pof.PACKAGE + ':id/create_account_first_name_next'))),
            'first-name')
        self.assertEqual(pof.classify(screen(node('Woman'), node('Man'),
                                             node('Show gender on my profile'))), 'gender')

    def test_sanitizer_removes_credentials_phone_code_and_unknown_text(self):
        xml = screen(
            node('Email address'),
            node('private@example.test', **{'class': 'android.widget.EditText'}),
            node('Secret9!', **{'class': 'android.widget.EditText', 'password': 'true'}),
            node('5551234567', **{'class': 'android.widget.EditText'}),
            node('123456', **{'class': 'android.widget.EditText'}),
            node('unreviewed server message'))
        clean = pof.sanitized_xml(xml)
        self.assertIn('Email address', clean)
        for secret in ('private@example.test', 'Secret9!', '5551234567', '123456',
                       'unreviewed server message'):
            self.assertNotIn(secret, clean)

    def test_notification_action_uses_exact_permission_control(self):
        package = 'com.android.permissioncontroller'
        xml = screen(
            node('Allow POF to send you notifications?', package),
            node('Allow', package, resource_id='com.android.permissioncontroller:id/permission_allow_button',
                 enabled='true', clickable='true', bounds='[0,0][100,80]'))
        calls = []
        with patch.object(pof, 'read_ui', return_value=xml), \
                patch.object(pof, 'adb_call', side_effect=lambda *args: calls.append(args) or ''):
            pof.allow_notifications('serial')
        self.assertEqual(calls, [('serial', 'shell', 'input', 'tap', '50', '40')])

    def test_first_name_is_verified_before_next_and_not_saved(self):
        prompt = screen(
            node('Let’s get started.'), node('First name'),
            node('What can we call you?', resource_id=pof.PACKAGE + ':id/first_name',
                 **{'class': 'android.widget.EditText', 'enabled': 'true',
                    'clickable': 'true', 'bounds': '[0,0][200,100]'}),
            node('Let’s go', resource_id=pof.PACKAGE + ':id/create_account_first_name_next',
                 enabled='true', clickable='true', bounds='[0,100][200,200]'))
        entered = prompt.replace('What can we call you?', 'Bella')
        calls = []
        with patch.object(pof, 'read_ui', side_effect=[prompt, entered]), \
                patch.object(pof, 'adb_call', side_effect=lambda *args: calls.append(args) or ''):
            pof.submit_first_name('serial', 'Bella')
        self.assertEqual(calls, [
            ('serial', 'shell', 'dumpsys', 'input_method'),
            ('serial', 'shell', 'input', 'tap', '100', '50'),
            ('serial', 'shell', 'input', 'text', 'Bella'),
            ('serial', 'shell', 'input', 'tap', '100', '150'),
        ])

    def test_pledge_acceptance_is_explicit_and_exact(self):
        xml = screen(
            node('Be real.'), node('Be kind.'), node('Be respectful.'), node('Be safe.'),
            node('Got it', resource_id=pof.PACKAGE + ':id/acq_funnel_pledge_i_pledge',
                 enabled='true', clickable='true', bounds='[0,0][200,100]'))
        calls = []
        with patch.object(pof, 'read_ui', return_value=xml), \
                patch.object(pof, 'adb_call', side_effect=lambda *args: calls.append(args) or ''):
            pof.accept_pledge('serial')
        self.assertEqual(calls, [('serial', 'shell', 'input', 'tap', '100', '50')])

    def test_runner_stops_without_action_at_photo_boundary(self):
        xml = screen(node('Show those pearly whites.'),
                     node('Time to share that lovely face with the world.'))
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pof, '_validate_device'), \
                patch.object(pof, 'read_ui', return_value=xml), \
                patch.object(pof, 'adb_call') as adb:
            self.assertEqual(pof.run_signup('serial', 'avd', folder), 2)
            adb.assert_called_once_with('serial', 'shell', 'dumpsys', 'input_method')
            self.assertEqual((Path(folder) / 'status.json').read_text().count('photo-manual-stop'), 2)

    def test_runner_waits_for_transient_unknown_before_permission(self):
        blank = screen(node(''))
        permission = screen(
            node('Allow POF to send you notifications?', 'com.android.permissioncontroller'),
            node('Allow', 'com.android.permissioncontroller',
                 resource_id='com.android.permissioncontroller:id/permission_allow_button',
                 enabled='true', clickable='true', bounds='[0,0][100,80]'))
        welcome = screen(node('Create account'), node('Sign in'))
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pof, '_validate_device'), \
                patch.object(pof, 'read_ui', side_effect=[blank, permission, permission, welcome]), \
                patch.object(pof, 'adb_call'), \
                patch.object(pof.time, 'sleep'):
            self.assertEqual(pof.run_signup('serial', 'avd', folder, notifications=True), 2)
            self.assertEqual(pof.classify(welcome), 'welcome')


if __name__ == '__main__':
    unittest.main()
