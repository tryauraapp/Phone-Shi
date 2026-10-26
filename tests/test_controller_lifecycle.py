import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from controller_lifecycle import stop_controller


class ControllerLifecycleTests(unittest.TestCase):
    def test_live_controller_stops_and_releases_lock_with_spaces_in_paths(self):
        for kind, flag in [('signal', '--profile'), ('location', '--output')]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='phone setup ') as folder:
                root = Path(folder).resolve()
                script = root / f'emulator_{kind}_sim.py'
                state, lock, owner = root / 'state.json', root / 'runtime.lock', root / 'owner path'
                script.write_text('''import fcntl, json, os, pathlib, time
root = pathlib.Path(__file__).parent
with (root / 'runtime.lock').open('a+') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    (root / 'state.json').write_text(json.dumps({'avd': 'phone', 'pid': os.getpid()}))
    time.sleep(60)
''')
                child = subprocess.Popen([sys.executable, '-I', str(script), '--avd', 'phone', flag, str(owner)])
                try:
                    deadline = time.monotonic() + 5
                    while not state.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(state.exists(), 'Controller did not start')
                    stop_controller('phone', state, lock, script, flag, owner, timeout=2)
                    child.wait(timeout=2)
                    self.assertNotEqual(child.returncode, 0)
                    with lock.open('a+') as stream:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=2)

    def test_released_lock_never_signals_stale_or_reused_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, state = root / 'runtime.lock', root / 'state.json'
            lock.touch()
            state.write_text(json.dumps({'avd': 'phone', 'pid': os.getpid()}))
            with patch('controller_lifecycle.os.kill') as kill:
                stop_controller('phone', state, lock, root / 'script.py', '--output', root)
            kill.assert_not_called()

    def test_held_lock_with_unrelated_process_never_signals_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, state = root / 'runtime.lock', root / 'state.json'
            state.write_text(json.dumps({'avd': 'phone', 'pid': os.getpid()}))
            with lock.open('a+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                with patch('controller_lifecycle.os.kill') as kill:
                    with self.assertRaisesRegex(RuntimeError, 'another process'):
                        stop_controller('phone', state, lock, root / 'script.py', '--output', root)
                kill.assert_not_called()

    def test_held_lock_for_another_phone_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, state = root / 'runtime.lock', root / 'state.json'
            state.write_text(json.dumps({'avd': 'other-phone', 'pid': os.getpid()}))
            with lock.open('a+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                with patch('controller_lifecycle.os.kill') as kill:
                    with self.assertRaisesRegex(RuntimeError, 'does not identify this phone'):
                        stop_controller('phone', state, lock, root / 'script.py', '--output', root)
                kill.assert_not_called()

