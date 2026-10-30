import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import shlex

from setup_vps_phone import DEFAULT_PROFILE, apply_runtime, config, finish, launcher, read, save, scan_counts, shell, validate_request


class StandardSetupTests(unittest.TestCase):
    def test_runtime_recovers_a_late_emulator_rotation_reset_before_becoming_ready(self):
        reads = iter(['1'] + ['0'] * 6)
        commands = []
        def device(meta, *args):
            commands.append(args)
            if args == ('settings', 'get', 'system', 'accelerometer_rotation'):
                return next(reads)
            if args == ('settings', 'get', 'system', 'user_rotation'):
                return '0'
            return ''
        with patch('setup_vps_phone.wait_boot'), patch('setup_vps_phone.console'), \
             patch('setup_vps_phone.shell', side_effect=device), \
             patch('setup_vps_phone.time.sleep'), patch('setup_vps_phone.time.monotonic', return_value=0):
            apply_runtime({}, read(DEFAULT_PROFILE))
        self.assertGreaterEqual(commands.count(('cmd', 'window', 'user-rotation', 'lock', '0')), 2)

    def test_runtime_fails_if_the_requested_portrait_setting_never_stabilizes(self):
        with patch('setup_vps_phone.wait_boot'), patch('setup_vps_phone.console'), \
             patch('setup_vps_phone.shell', return_value='1'), patch('setup_vps_phone.time.sleep'), \
             patch('setup_vps_phone.time.monotonic', side_effect=range(100)):
            with self.assertRaisesRegex(RuntimeError, 'did not stabilize'):
                apply_runtime({}, read(DEFAULT_PROFILE))

    def test_provisioning_flushes_guest_storage_before_the_host_restart(self):
        profile = read(DEFAULT_PROFILE)
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            meta = dict(directory=tmp, sdk='/sdk', port=5562, name='Phone_A', service='android-phone-5562.service')
            with patch('setup_vps_phone.sha', return_value=profile['duck']['sha256']), \
                 patch('setup_vps_phone.call', side_effect=lambda *a, **kw: events.append(('host', a))), \
                 patch('setup_vps_phone.shell', side_effect=lambda m, *a: events.append(('guest', a))), \
                 patch('setup_vps_phone.wait_boot'), patch('setup_vps_phone.capture_android_id'), \
                 patch('setup_vps_phone.verify_runtime', return_value={'verified': True}):
                finish(meta, profile, '/duck.apk')
            restart = events.index(('host', ('systemctl', 'restart', 'android-phone-5562.service')))
            self.assertEqual(events[restart - 1], ('guest', ('sync',)))
            saved = read(Path(tmp) / 'setup-complete.json')
            self.assertTrue(saved['automated_base_complete'])
            self.assertFalse(saved['full_setup_complete'])
            self.assertEqual(saved['steps'][-1]['status'], 'pending')

    def test_scan_review_rejects_missing_pending_wrong_build_and_changed_counts(self):
        profile = read(DEFAULT_PROFILE)
        report = 'App Version : example (Build 1097)\n[✖] Danger : 3\n[▲] Warning : 3\n[✔] Ready : 20\n[·] Pending : 0\n'
        self.assertEqual(scan_counts(report, profile), profile['duck']['comparison_baseline'])
        for invalid in [report.replace('Pending : 0', 'Pending : 1'),
                        report.replace('[·] Pending : 0\n', ''), report.replace('1097', '1098'),
                        report.replace('Danger : 3', 'Danger : 4')]:
            with self.assertRaises(ValueError):
                scan_counts(invalid, profile)

    def test_adb_settings_values_with_spaces_survive_the_remote_shell(self):
        meta = dict(sdk='/opt/sdk', port=5562)
        with patch('setup_vps_phone.call', return_value='') as command:
            shell(meta, 'settings', 'put', 'global', 'device_name', 'Galaxy S25')
        args = command.call_args.args
        self.assertEqual(args[:4], ('/opt/sdk/platform-tools/adb', '-s', 'emulator-5562', 'shell'))
        self.assertEqual(shlex.split(args[4]), ['settings', 'put', 'global', 'device_name', 'Galaxy S25'])

    def test_rejects_names_and_ports_that_could_target_other_files_or_controls(self):
        for name, port, grpc in [('../phone', 5562, 8562), ('phone', 5555, 8562),
                                  ('phone', 5562, 5563), ('phone\nExecStart=bad', 5562, 8562)]:
            with self.assertRaises(ValueError):
                validate_request(name, port, grpc)
        validate_request('Fresh_Phone_1', 5562, 8562)

    def test_launch_scopes_userdata_identity_ports_and_security_to_the_new_phone(self):
        profile = read(DEFAULT_PROFILE)
        meta = dict(name='Phone_A', root='/opt/phones', sdk='/opt/sdk', avd_dir='/opt/phones/avd/Phone_A.avd',
                    registry='/opt/phones/ids.sqlite3', port=5562, grpc_port=8562)
        result = launcher(meta, profile)
        for value in ['--avd Phone_A', '--avd-dir /opt/phones/avd/Phone_A.avd', '-port 5562',
                      '-grpc 8562 -grpc-use-token', '-feature -GLAsyncSwap', '-no-snapshot', '-timezone GMT']:
            self.assertIn(value, result)
        self.assertNotIn('5556', result)
        self.assertNotIn('wipe-data', result)
        self.assertNotIn('writable-system', result)
        self.assertIn('AvdId=Phone_A\n', config('Phone_A', profile))
        self.assertEqual([s['id'] for s in profile['steps']], list(range(1, 35)))

    def test_saved_record_is_private_and_atomic_replacement_preserves_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'phone.json'
            save(path, {'name': 'Phone_A'})
            save(path, {'name': 'Phone_B'})
            self.assertEqual(read(path), {'name': 'Phone_B'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_name('phone.json.tmp').exists())


if __name__ == '__main__':
    unittest.main()
