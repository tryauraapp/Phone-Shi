import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import restore_phone_runtime as runtime


class RuntimeRestoreTests(unittest.TestCase):
    def write_runtime(self, root, checks=None):
        work = Path(root) / 'Phone_A/setup'
        (work / 'profile').mkdir(parents=True)
        required = {'cellular-lte', 'battery-simulation', 'signal-simulation',
                    'bounded-gps', 'root-isolation'}
        (work / 'setup-complete.json').write_text(json.dumps({
            'schema': 1, 'avd': 'Phone_A',
            'completedChecks': sorted(required if checks is None else checks),
            'authorizedSignupPackages': []}))
        (work / 'proxy-location.json').write_text(json.dumps({
            'ip': '192.0.2.8', 'latitude': 33.7486, 'longitude': -84.388,
            'timezone': 'America/New_York'}))
        (work / 'profile/device-profile.json').write_text('{}')
        return work

    def test_loads_complete_certified_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_runtime(directory)
            loaded = runtime.load_runtime('Phone_A', directory)
            self.assertEqual(loaded['timezone'], 'America/New_York')
            self.assertEqual(loaded['location']['latitude'], 33.7486)

    def test_missing_or_incomplete_certificate_is_not_restorable(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(runtime.load_runtime('Phone_A', directory))
            self.write_runtime(directory, {'cellular-lte'})
            with self.assertRaisesRegex(ValueError, 'every runtime service'):
                runtime.load_runtime('Phone_A', directory)

    def test_invalid_proxy_location_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            work = self.write_runtime(directory)
            (work / 'proxy-location.json').write_text(json.dumps({
                'latitude': 91, 'longitude': 0, 'timezone': 'Invalid/Zone'}))
            with self.assertRaisesRegex(ValueError, 'invalid'):
                runtime.load_runtime('Phone_A', directory)

    def test_restores_and_verifies_saved_android_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            avd = Path(directory) / 'Phone_A.avd'
            avd.mkdir()
            (avd / 's25-identifiers.json').write_text(json.dumps({
                'avd': 'Phone_A', 'system_settings': {
                    'screen_brightness': '123', 'screen_off_timeout': '60000'}}))
            observed = {'screen_brightness': '123', 'screen_off_timeout': '60000'}
            def fake_call(command, timeout=30):
                if command[-3:] == ['get', 'system', 'screen_brightness']:
                    return observed['screen_brightness'] + '\n'
                if command[-3:] == ['get', 'system', 'screen_off_timeout']:
                    return observed['screen_off_timeout'] + '\n'
                if command[-2:] == ['getprop', 'persist.sys.timezone']:
                    return 'America/New_York\n'
                if command[-1:] == ['is-location-enabled']:
                    return 'true\n'
                return ''
            with patch.dict('os.environ', {'ANDROID_AVD_HOME': directory}), \
                    patch.object(runtime, 'call', side_effect=fake_call) as call:
                runtime.restore_android_settings('adb', 'emulator-5554', 'Phone_A',
                                                 'America/New_York')
            commands = [item.args[0] for item in call.call_args_list]
            self.assertTrue(any('screen_off_timeout' in command and 'put' in command
                                for command in commands))
            self.assertTrue(any(command[-1] == 'true' for command in commands))


if __name__ == '__main__':
    unittest.main()
