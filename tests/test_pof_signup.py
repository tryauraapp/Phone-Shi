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
            'welcome': screen(node('Create account'), node('Sign in')),
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
            adb.assert_not_called()
            self.assertEqual((Path(folder) / 'status.json').read_text().count('photo-manual-stop'), 2)


if __name__ == '__main__':
    unittest.main()
