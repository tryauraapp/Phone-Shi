import json
import unittest
from pathlib import Path
import subprocess
import sys
import tempfile

from prepare_camera_video import DEFAULT_PROFILE, framing_filter


class CameraFramingTests(unittest.TestCase):
    def test_vp9_profile_is_webm_all_intra_and_dry_run_leaves_input_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'input with spaces.mp4'
            video.write_bytes(b'fixture')
            output = Path(folder) / 'prepared.webm'
            result = subprocess.run([sys.executable, str(DEFAULT_PROFILE.parents[1] / 'prepare_camera_video.py'),
                                     str(video), str(output), '--codec', 'vp9', '--dry-run'],
                                    capture_output=True, text=True, check=True)
            command = json.loads(result.stdout)['command']
            self.assertIn('libvpx-vp9', command)
            self.assertEqual(command[command.index('-g') + 1], '1')
            self.assertFalse(output.exists())
            self.assertEqual(video.read_bytes(), b'fixture')

    def test_fps_resamples_before_framing(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'input.mp4'
            video.write_bytes(b'fixture')
            result = subprocess.run([sys.executable, str(DEFAULT_PROFILE.parents[1] / 'prepare_camera_video.py'),
                                     str(video), str(Path(folder) / 'out.webm'), '--codec', 'vp9',
                                     '--fps', '30', '--dry-run'], capture_output=True, text=True, check=True)
            record = json.loads(result.stdout)
            self.assertEqual(record['fps'], 30)
            self.assertTrue(record['filter'].startswith('fps=30,scale='))
            default = subprocess.run([sys.executable, str(DEFAULT_PROFILE.parents[1] / 'prepare_camera_video.py'),
                                      str(video), str(Path(folder) / 'out2.webm'), '--dry-run'],
                                     capture_output=True, text=True, check=True)
            self.assertIsNone(json.loads(default.stdout)['fps'])

    def test_saved_framing(self):
        profile = json.loads(DEFAULT_PROFILE.read_text())
        filters, visible = framing_filter(profile["preview_size"],
                                          profile["canvas_size"],
                                          profile["vertical_anchor"])
        self.assertEqual(visible, (720, 960))
        self.assertIn("scale=720:960:force_original_aspect_ratio=increase", filters)
        self.assertIn("*0.40625/2", filters)
        self.assertIn("pad=1280:960:0:0:black", filters)

    def test_ratio_comes_from_preview_not_phone_screen(self):
        for preview, expected in [((1080, 1920), (540, 960)),
                                  ((1920, 1080), (1280, 720)),
                                  ((1000, 1000), (960, 960))]:
            with self.subTest(preview=preview):
                _, visible = framing_filter(preview, (1280, 960), 0.5)
                self.assertEqual(visible, expected)
                self.assertEqual(visible[0] * preview[1], visible[1] * preview[0])

    def test_invalid_geometry_rejected(self):
        for preview, canvas, anchor in [((0, 10), (1280, 960), 0.5),
                                         ((3, 4), (1279, 960), 0.5),
                                         ((3, 4), (1280, 960), -0.1),
                                         ((3, 4), (1280, 960), float("nan"))]:
            with self.subTest(preview=preview, canvas=canvas, anchor=anchor):
                with self.assertRaises(ValueError):
                    framing_filter(preview, canvas, anchor)
