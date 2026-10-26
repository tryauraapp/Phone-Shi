import unittest
from pathlib import Path

import cv2
import numpy as np

import live_face_track as track


class LiveFaceTrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = track.make_detector(
            Path(track.__file__).with_name("models") / "blaze_face_short_range.tflite", 0.4)

    @classmethod
    def tearDownClass(cls):
        cls.detector.close()

    def test_detects_real_app_oval_and_screen_space_error_when_fixture_available(self):
        fixture = Path("/tmp/tinder-window-current2.png")
        if not fixture.is_file():
            self.skipTest("live emulator capture is not present")
        measurement = track.measure_alignment(cv2.imread(str(fixture)), self.detector)
        self.assertIsNotNone(measurement)
        self.assertGreater(measurement["error_x"], 0.05)
        self.assertGreater(measurement["error_y"], 0.02)
        self.assertGreater(measurement["face_fill"], 0.2)

    def test_camera_layer_preserves_ratio_and_moves_the_whole_image(self):
        source = np.zeros((160, 90, 3), dtype=np.uint8)
        source[60:100, 35:55] = 255
        centered = track.camera_layer_frame(source, 120, 80, 0, 0, 1)
        moved = track.camera_layer_frame(source, 120, 80, 0.2, -0.1, 1)
        self.assertEqual(centered.shape, (80, 120, 3))
        center_points = np.argwhere(centered[:, :, 0] > 200).mean(axis=0)
        moved_points = np.argwhere(moved[:, :, 0] > 200).mean(axis=0)
        self.assertGreater(moved_points[1], center_points[1])
        self.assertLess(moved_points[0], center_points[0])

    def test_small_instructional_ellipse_is_not_a_live_guide(self):
        image = np.full((900, 440, 3), 255, dtype=np.uint8)
        cv2.ellipse(image, (285, 340), (60, 95), 0, 0, 360, (0, 0, 220), 4)
        self.assertIsNone(track.detect_oval(image))

    def test_obs_transform_scales_up_for_move_closer_and_down_for_move_away(self):
        state = track.ControlState(position_x=0.0, position_y=0.0, scale=1.18)
        closer_m = {
            "error_x": 0.0,
            "error_y": 0.0,
            "face_fill": 0.30,
            "instruction": "move_closer",
            "move_closer": True,
        }
        _px, _py, scale_up = track.compute_next_obs_transform(state, closer_m)
        self.assertGreater(scale_up, state.scale)

        away_m = {
            "error_x": 0.0,
            "error_y": 0.0,
            "face_fill": 0.42,
            "instruction": "move_away",
            "move_closer": False,
        }
        _px, _py, scale_down = track.compute_next_obs_transform(state, away_m)
        self.assertLess(scale_down, state.scale)

        steady_m = {
            "error_x": 0.0,
            "error_y": 0.0,
            "face_fill": 0.36,
            "instruction": "hold_steady",
            "move_closer": False,
        }
        _px, _py, scale_steady = track.compute_next_obs_transform(state, steady_m)
        self.assertEqual(scale_steady, state.scale)

    def test_smooth_transform_animator_interpolates_60hz_without_step_jumps(self):
        class DummyOBS:
            canvas_width = 1080.0
            canvas_height = 1440.0

            def set_transform(self, x, y, s):
                pass

        anim = track.SmoothTransformAnimator(
            obs=DummyOBS(),
            init_x=100.0,
            init_y=50.0,
            init_scale=1.16,
            base_scale=1.0,
            fps=60.0,
            sway_enabled=False,
        )
        state = track.ControlState(position_x=100.0, position_y=50.0, scale=1.16)
        closer_m = {
            "error_x": 0.05,
            "error_y": -0.04,
            "face_fill": 0.32,
            "instruction": "move_closer",
            "move_closer": True,
        }
        tx, ty, ts = track.compute_next_obs_transform(state, closer_m)
        anim.set_target(tx, ty, ts, instruction="move_closer")
        scales = [1.16]
        for i in range(1, 25):
            _x, _y, s = anim.step_dt(1.0 / 60.0, i / 60.0)
            scales.append(s)
        deltas = [scales[i + 1] - scales[i] for i in range(len(scales) - 1)]
        self.assertTrue(all(0.0 < d < 0.008 for d in deltas))
        self.assertGreater(scales[-1], 1.20)
        self.assertLess(scales[-1], ts)


if __name__ == "__main__":
    unittest.main()
