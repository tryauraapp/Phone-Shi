import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import phone_setup_guard as guard


def completed(command, output=''):
    return subprocess.CompletedProcess(command, 0, output, '')


class PhoneSetupGuardTests(unittest.TestCase):
    def make_work(self, root):
        work = Path(root)
        for name in guard.REQUIRED_ARTIFACTS + guard.RUNTIME_ARTIFACTS:
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == 'checker-report.json':
                path.write_text(json.dumps({
                    'redFlags': 0,
                    'weakSignals': 1,
                    'findings': [
                        {'name': 'Network topology', 'severity': 'NOT OBSERVED',
                         'evidence': 'Transport=CELLULAR Data network=LTE'},
                        {'name': 'Root binaries', 'severity': 'NOT OBSERVED', 'evidence': ''},
                    ],
                }))
            else:
                path.write_text('fixture-' + name)
        return work

    def adb(self, command, **kwargs):
        args = command[3:]
        if args == ['shell', 'getprop', 'ro.boot.qemu.avd_name']:
            output = 'test-avd\n'
        elif args == ['shell', 'getprop', 'sys.boot_completed']:
            output = '1\n'
        elif args == ['shell', 'getprop', 'ro.product.cpu.abilist']:
            output = 'arm64-v8a,armeabi-v7a\n'
        elif args == ['shell', 'getprop', 'ro.product.manufacturer']:
            output = 'samsung\n'
        elif args == ['shell', 'getprop', 'ro.product.model']:
            output = 'SM-S931B\n'
        elif args == ['shell', 'pm', 'path', 'com.pof.android']:
            output = 'package:/data/app/com.pof.android/base.apk\n'
        elif args == ['shell', 'su', '-c', 'id -u']:
            output = '0\n'
        elif args == ['shell', 'su', '-c', 'magisk --denylist ls']:
            output = 'com.pof.android|com.pof.android\n'
        else:
            raise AssertionError(args)
        return completed(command, output)

    def test_record_then_verify_binds_artifacts_avd_package_and_live_checks(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(guard.subprocess, 'run', side_effect=self.adb):
            work = self.make_work(folder)
            manifest = guard.record_phone_setup('serial', 'test-avd', work, ['com.pof.android'])
            result = guard.verify_phone_setup('serial', 'test-avd', 'com.pof.android', manifest)
            self.assertEqual(result['checker']['redFlags'], 0)
            self.assertIn('root-isolation', result['completedChecks'])

    def test_mutable_runtime_state_can_change_after_certification(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(guard.subprocess, 'run', side_effect=self.adb):
            work = self.make_work(folder)
            manifest = guard.record_phone_setup('serial', 'test-avd', work, ['com.pof.android'])
            (work / 'profile/radio-state.json').write_text('new live state')
            guard.verify_phone_setup('serial', 'test-avd', 'com.pof.android', manifest)

    def test_changed_artifact_blocks_signup(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(guard.subprocess, 'run', side_effect=self.adb):
            work = self.make_work(folder)
            manifest = guard.record_phone_setup('serial', 'test-avd', work, ['com.pof.android'])
            (work / 'profile/device-profile.json').write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
                guard.verify_phone_setup('serial', 'test-avd', 'com.pof.android', manifest)

    def test_missing_certificate_and_uncertified_package_block_signup(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'certificate is missing'):
                guard.verify_phone_setup('serial', 'test-avd', 'com.pof.android', Path(folder) / 'missing.json')
            with patch.object(guard.subprocess, 'run', side_effect=self.adb):
                work = self.make_work(folder)
                manifest = guard.record_phone_setup('serial', 'test-avd', work, ['com.pof.android'])
                with self.assertRaisesRegex(RuntimeError, 'not certified'):
                    guard.verify_phone_setup('serial', 'test-avd', 'com.bumble.app', manifest)

    def test_record_can_precede_app_install_but_verify_cannot(self):
        def without_package(command, **kwargs):
            if command[3:] == ['shell', 'pm', 'path', 'com.pof.android']:
                return completed(command)
            return self.adb(command, **kwargs)

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(guard.subprocess, 'run', side_effect=without_package):
            work = self.make_work(folder)
            manifest = guard.record_phone_setup('serial', 'test-avd', work, ['com.pof.android'])
            data = json.loads(manifest.read_text())
            self.assertEqual(data['pendingSignupPackages'], ['com.pof.android'])
            with self.assertRaisesRegex(RuntimeError, 'not installed'):
                guard.verify_phone_setup('serial', 'test-avd', 'com.pof.android', manifest)


if __name__ == '__main__':
    unittest.main()
