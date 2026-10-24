from pathlib import Path
import tempfile
import unittest
import struct
import json
from unittest.mock import patch

from native_video_camera import animation_enabled_text, preflight, reject_experimental_engine, running_serial, has_live_lock, record_verification


class NativeCameraTests(unittest.TestCase):
    def test_failed_process_cannot_reuse_an_old_success_report(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            camera = home / 'Test.avd/camera'
            camera.mkdir(parents=True)
            profile = camera / 'native-camera.json'
            profile.write_text(json.dumps({'source_sha256': 'source'}))
            report = home / 'report.json'
            report.write_text(json.dumps({'avd': 'Test', 'status': 'passed', 'motion_verified': True}))
            self.assertFalse(record_verification('Test', {'ANDROID_AVD_HOME': folder}, report, 'camera2_reader', 1))
            self.assertEqual(json.loads(profile.read_text())['status'], 'verification_failed')
            self.assertTrue(record_verification('Test', {'ANDROID_AVD_HOME': folder}, report, 'camera2_reader', 0))
            self.assertEqual(json.loads(profile.read_text())['status'], 'verified_camera2_pixels')

    def test_running_lookup_uses_avd_identity_not_the_first_connected_serial(self):
        responses = [b'List of devices attached\nemulator-5554\tdevice\nemulator-5556\tdevice\nphysical\tdevice\n',
                     b'Other\nOK\n', b'Test\nOK\n']
        with patch('native_video_camera.subprocess.check_output', side_effect=responses) as run:
            self.assertEqual(running_serial('Test'), 'emulator-5556')
            self.assertEqual(run.call_count, 3)

    def test_live_shutdown_lock_blocks_configuration_even_after_adb_disconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'hardware-qemu.ini.lock').write_text('12345\n')
            with patch('native_video_camera.os.kill') as kill:
                self.assertTrue(has_live_lock(directory))
                kill.assert_called_once_with(12345, 0)
            with patch('native_video_camera.os.kill', side_effect=ProcessLookupError):
                self.assertFalse(has_live_lock(directory))
    def test_abandoned_binary_patch_is_rejected_not_reapplied(self):
        with tempfile.TemporaryDirectory() as folder:
            avd = Path(folder)
            engine = avd / 's25-emulator/qemu/darwin-aarch64/qemu-system-aarch64'
            engine.parent.mkdir(parents=True)
            patch = struct.pack('<6I', 0xD10343FF, 0xF940180B, 0x52856CE9,
                                0x8B090161, 0xF9402409, 0xF9422529)
            engine.write_bytes(b'fixture' + patch)
            with self.assertRaisesRegex(ValueError, 'experimental camera patch'):
                reject_experimental_engine(avd)
            self.assertEqual(engine.read_bytes(), b'fixture' + patch)
            engine.write_bytes(b'clean fixture')
            reject_experimental_engine(avd)

    def test_setting_preserves_sections_and_is_idempotent(self):
        original = '[perAvd]\nloc\\latitude=5\nvirtualscene\\tv_animation=false\n[other]\nvalue=123\n'
        updated = animation_enabled_text(original)
        self.assertIn('loc\\latitude=5', updated)
        self.assertIn('[other]\nvalue=123', updated)
        self.assertEqual(updated.count('virtualscene\\tv_animation='), 1)
        self.assertEqual(updated, animation_enabled_text(updated))

    def test_missing_section_and_duplicate_keys(self):
        self.assertEqual(animation_enabled_text(''), '[perAvd]\nvirtualscene\\tv_animation=true\n')
        text = '[perAvd]\nvirtualscene\\tv_animation=false\nvirtualscene\\tv_animation=false\n'
        self.assertEqual(animation_enabled_text(text).count('virtualscene\\tv_animation='), 1)

    def test_only_video_front_camera_is_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            avd = home / 'Test.avd'
            avd.mkdir()
            config = avd / 'config.ini'
            config.write_text('hw.camera.front=emulated\nhw.camera.back=none\n')
            env = {'ANDROID_AVD_HOME': folder}
            self.assertIsNone(preflight('Test', env, []))
            self.assertFalse((avd / 'AVD.conf').exists())
            video = home / 'a video.mp4'
            video.write_bytes(b'test fixture')
            self.assertEqual(preflight('Test', env, ['-camera-front', 'videofile:' + str(video)]), video.resolve())
            self.assertEqual(config.read_text(), 'hw.camera.front=emulated\nhw.camera.back=none\n')

    def test_missing_video_fails_before_settings_are_written(self):
        with tempfile.TemporaryDirectory() as folder:
            avd = Path(folder) / 'Test.avd'
            avd.mkdir()
            (avd / 'config.ini').write_text('hw.camera.front=videofile:/missing/video.mp4\n')
            with self.assertRaises(ValueError):
                preflight('Test', {'ANDROID_AVD_HOME': folder}, [])
            self.assertFalse((avd / 'AVD.conf').exists())

    def test_environment_video_front_camera_uses_its_scene_source(self):
        with tempfile.TemporaryDirectory() as folder:
            avd = Path(folder) / 'Test.avd'
            avd.mkdir()
            video = avd / 'prepared.webm'
            video.write_bytes(b'fixture')
            (avd / 'config.ini').write_text('hw.camera.front=environment\n')
            (avd / 'environment.ini').write_text('scene.mode=videofile:' + str(video) + '\nbackground.enabled=false\n')
            self.assertEqual(preflight('Test', {'ANDROID_AVD_HOME': folder}, []), video.resolve())
