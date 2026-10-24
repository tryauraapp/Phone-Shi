from pathlib import Path
import tempfile
import unittest

from configure_video_camera import digest, ini_values, save


class CameraConfigurationTests(unittest.TestCase):
    def test_camera_update_preserves_identity_and_unrelated_settings(self):
        original = 'AvdId=Test\nhw.camera.front=none\nhw.camera.front=emulated\ncustom=keep\n'
        result = ini_values(original, {'hw.camera.front': 'environment', 'hw.camera.back': 'emulated'})
        self.assertIn('AvdId=Test', result)
        self.assertIn('custom=keep', result)
        self.assertEqual(result.count('hw.camera.front='), 1)
        self.assertEqual(result, ini_values(result, {'hw.camera.front': 'environment', 'hw.camera.back': 'emulated'}))

    def test_first_backup_survives_reconfiguration_and_identical_save_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.ini'
            path.write_text('original\n')
            save(path, 'first\n')
            stamp = path.stat().st_mtime_ns
            save(path, 'first\n')
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            save(path, 'second\n')
            self.assertEqual(path.with_name('config.ini.before-native-camera-profile').read_text(), 'original\n')

    def test_original_media_checksum_is_streamed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'video'
            path.write_bytes(b'abc')
            self.assertEqual(digest(path), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
