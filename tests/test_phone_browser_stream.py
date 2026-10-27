import unittest
from unittest.mock import patch
from phone_browser_stream import AwakeLeases, PhoneStream


class ViewerLifecycleTests(unittest.TestCase):
    def test_multiple_viewers_preserve_original_timeout_until_last_lease_expires(self):
        # Avoid background threads in this deterministic lifecycle test.
        with patch('phone_browser_stream.threading.Thread'), \
             patch('phone_browser_stream.atexit.register'), \
             patch('phone_browser_stream.adb', return_value=b'60000\n') as adb, \
             patch('phone_browser_stream.time.monotonic', return_value=100):
            leases = AwakeLeases()
            leases.touch('emulator-5556')
            leases.touch('emulator-5556')
            self.assertEqual(leases.phones['emulator-5556'], ['60000', 145])
            self.assertEqual(adb.call_count, 3)
            leases.close()
            adb.assert_called_with('emulator-5556', 'shell', 'settings', 'put',
                                   'system', 'screen_off_timeout', '60000')

    def test_slow_viewer_is_disconnected_without_blocking_other_viewers(self):
        with patch('phone_browser_stream.threading.Thread'):
            stream = PhoneStream('emulator-5556')
        slow, fast = stream.subscribe(), stream.subscribe()
        stream.publish(b'init', initial=True)
        fast.get_nowait()
        for _ in range(180):
            stream.publish(b'frame', keyframe=True)
            fast.get_nowait()
        self.assertNotIn(slow, stream.listeners)
        self.assertIn(fast, stream.listeners)
        self.assertIsNone(slow.get_nowait())

    def test_new_viewer_receives_init_and_latest_keyframe_group(self):
        with patch('phone_browser_stream.threading.Thread'):
            stream = PhoneStream('emulator-5556')
        stream.publish(b'init', initial=True)
        stream.publish(b'old-key', keyframe=True)
        stream.publish(b'new-key', keyframe=True)
        stream.publish(b'delta')
        viewer = stream.subscribe()
        self.assertEqual([viewer.get_nowait() for _ in range(3)],
                         [b'init', b'new-key', b'delta'])
