import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('avd_doctor', Path(__file__).resolve().parents[1] / 'mac_avd_doctor.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class AvdDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.avd = self.root / 'copied phone' / 'Phone.avd'
        self.avd.mkdir(parents=True)
        (self.avd / 'config.ini').write_text('AvdId=Phone\ntarget=android-35\nimage.sysdir.1=system-images/android-35/google_apis_playstore/arm64-v8a/\n')
        self.home = self.root / 'studio avds'

    def test_register_missing_pointer_preserves_userdata_and_config(self):
        userdata = self.avd / 'userdata-qemu.img'
        userdata.write_bytes(b'guest data')
        config = (self.avd / 'config.ini').read_bytes()
        ini, backup = doctor.register(self.avd, 'Phone', self.home)
        self.assertIsNone(backup)
        self.assertEqual(doctor.properties(ini)['path'], str(self.avd))
        self.assertEqual(userdata.read_bytes(), b'guest data')
        self.assertEqual((self.avd / 'config.ini').read_bytes(), config)
        self.assertIsNone(doctor.register(self.avd, 'Phone', self.home)[1])

    def test_stale_registration_backed_up_without_old_relative_fallback(self):
        self.home.mkdir()
        ini = self.home / 'Phone.ini'
        old = 'path=/missing/old-mac/Phone.avd\npath.rel=avd/Old.avd\n'
        ini.write_text(old)
        _, backup = doctor.register(self.avd, 'Phone', self.home)
        self.assertEqual(backup.read_text(), old)
        self.assertNotIn('path.rel', doctor.properties(ini))

    def test_live_name_collision_refused(self):
        other = self.root / 'other.avd'
        other.mkdir()
        self.home.mkdir()
        ini = self.home / 'Phone.ini'
        ini.write_text(f'path={other}\n')
        with self.assertRaisesRegex(ValueError, 'another existing device'):
            doctor.register(self.avd, 'Phone', self.home)
        self.assertEqual(doctor.properties(ini)['path'], str(other))

    def test_invalid_and_mismatched_names_refused(self):
        for name in ('../Phone', 'Other', 'Phone\npath=/tmp'):
            with self.assertRaises(ValueError):
                doctor.register(self.avd, name, self.home)
        self.assertFalse(self.home.exists())

    def test_all_discovery_locations_including_gui_default(self):
        roots = doctor.avd_roots({'ANDROID_AVD_HOME': str(self.root / 'custom'),
                                  'ANDROID_USER_HOME': str(self.root / 'user'),
                                  'ANDROID_EMULATOR_HOME': str(self.root / 'emulator')}, self.root)
        self.assertEqual(roots, [self.root / 'custom', self.root / 'emulator/avd',
                                 self.root / 'user/avd', self.root / '.android/avd'])

    def test_missing_image_and_copied_engine_detected(self):
        (self.avd / 's25-identifiers.json').write_text('{"private_emulator":"/old/mac/engine"}')
        issues = doctor.inspect_avd(self.avd, self.root / 'sdk')
        self.assertTrue(any('System image' in item for item in issues))
        self.assertTrue(any('Private engine' in item for item in issues))

    def test_broken_sdk_symlinks_detected(self):
        private = self.avd / 's25-emulator'
        (private / 'qemu').mkdir(parents=True)
        (private / 'lib64').symlink_to(self.root / 'old-sdk/lib64')
        import json
        (self.avd / 's25-identifiers.json').write_text(json.dumps({'private_emulator': str(private)}))
        self.assertTrue(any('broken SDK symlinks' in item for item in doctor.inspect_avd(self.avd, self.root)))
