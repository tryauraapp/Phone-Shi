import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import swap_camera_video as swap


class SwapCameraVideoTests(unittest.TestCase):
    def phone(self, home, name, front='environment', record=None):
        avd = home / (name + '.avd')
        avd.mkdir()
        (home / (name + '.ini')).write_text(f'path={avd}\n')
        (avd / 'config.ini').write_text(f'AvdId={name}\nhw.camera.front={front}\n')
        if record is not None:
            (avd / 'camera').mkdir()
            (avd / 'camera/native-camera.json').write_text(json.dumps(record))
        return avd

    def test_status_reports_prepared_and_legacy_phones_without_touching_them(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.phone(home, 'A', record={'original': '/x/orig.mp4', 'prepared_video': '/x/front.webm',
                                          'status': 'verified_camera2_pixels', 'fps': 30})
            self.phone(home, 'B', front='videofile:/old/clip.mp4')
            native = swap.sibling('native_video_camera')
            env = {'ANDROID_AVD_HOME': folder}
            with patch.object(native, 'running_serial', return_value=None):
                a = swap.phone_status('A', env, native)
                b = swap.phone_status('B', env, native)
            self.assertEqual((a['clip'], a['prepared'], a['state'], a['running']),
                             ('/x/orig.mp4', '/x/front.webm', 'verified_camera2_pixels', None))
            self.assertEqual((b['clip'], b['state']), ('/old/clip.mp4', 'legacy_direct_videofile'))
            self.assertEqual(swap.lab_phones(env), ['A', 'B'])

    def test_last_json_record_wins(self):
        text = json.dumps({'preparer': 1}, indent=2) + '\n' + json.dumps({'prepared_video': '/x.webm'}, indent=2) + '\n'
        self.assertEqual(swap.last_json(text)['prepared_video'], '/x.webm')
        with self.assertRaises(ValueError):
            swap.last_json('no record')

    def test_running_phone_is_refused_without_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.phone(home, 'A')
            clip = home / 'clip.mp4'
            clip.write_bytes(b'x')
            script = Path(swap.__file__)
            env = dict(os.environ, ANDROID_AVD_HOME=folder, PATH=folder + os.pathsep + os.environ['PATH'])
            fake_adb = home / 'adb'
            fake_adb.write_text('#!/bin/sh\nif [ "$1" = devices ]; then printf "List of devices attached\\nemulator-5554\\tdevice\\n"; '
                                'else echo A; fi\n')
            fake_adb.chmod(0o755)
            result = subprocess.run([sys.executable, '-I', str(script), '--avd', 'A', '--video', str(clip)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--restart', result.stderr)
            self.assertFalse((home / 'A.avd/camera').exists())


if __name__ == '__main__':
    unittest.main()
