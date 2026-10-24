import unittest

from verify_camera_playback import meaningful_change, preview_bounds, require_camera_foreground, is_front_active


class PlaybackTests(unittest.TestCase):
    def test_frozen_frame_is_failure(self):
        self.assertFalse(meaningful_change(bytes([90] * 4096), bytes([90] * 4096)))

    def test_small_render_noise_is_not_motion(self):
        self.assertFalse(meaningful_change(bytes([90] * 4096), bytes([91] * 4096)))

    def test_small_indicator_is_not_motion(self):
        self.assertFalse(meaningful_change(bytes(4096), bytes([255] * 10 + [0] * 4086)))

    def test_substantial_motion_is_detected(self):
        self.assertTrue(meaningful_change(bytes(4096), bytes([12] * 512 + [0] * 3584)))

    def test_actual_preview_not_screen(self):
        xml = '<hierarchy><node bounds="[0,0][1080,2340]"/><node resource-id="com.android.camera2:id/progress_overlay" bounds="[0,588][1080,2028]"/></hierarchy>'
        self.assertEqual(preview_bounds(xml), (0, 588, 1080, 2028))

    def test_launcher_or_crash_is_not_a_camera_preview(self):
        with self.assertRaises(RuntimeError):
            preview_bounds('<hierarchy><node package="launcher" bounds="[0,0][1080,2340]"/></hierarchy>')

    def test_switching_to_launcher_mid_check_is_rejected(self):
        with self.assertRaises(RuntimeError):
            require_camera_foreground('topResumedActivity=ActivityRecord{ com.google.launcher/.Launcher }')
        require_camera_foreground('topResumedActivity=ActivityRecord{ com.android.camera2/com.android.camera.CameraActivity }')

    def test_front_camera_must_be_the_active_device_not_merely_present(self):
        dump = '(Camera ID: 10, Cost: 100)\n== Camera HAL device device@1.1/internal/10 (v1.1) ==\nFacing: Back\n== Camera HAL device device@1.1/internal/11 (v1.1) ==\nFacing: Front\n'
        self.assertFalse(is_front_active(dump))
        self.assertTrue(is_front_active(dump.replace('(Camera ID: 10,', '(Camera ID: 11,')))
