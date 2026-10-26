import subprocess
import unittest
from unittest.mock import Mock

from setup_ui import read_ui


class SetupUIRetryTests(unittest.TestCase):
    def test_transition_dump_timeouts_retry_then_return_real_screen(self):
        xml = '<hierarchy><node text="Next"/></hierarchy>'
        call = Mock(side_effect=[subprocess.CalledProcessError(137, 'adb'),
                                subprocess.TimeoutExpired('adb', 12), xml])
        pause = Mock()
        self.assertEqual(read_ui('test', call=call, pause=pause), xml)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(pause.call_count, 2)

    def test_unrelated_device_error_is_not_retried(self):
        call = Mock(side_effect=subprocess.CalledProcessError(1, 'adb'))
        with self.assertRaises(subprocess.CalledProcessError):
            read_ui('test', call=call, pause=Mock())
        self.assertEqual(call.call_count, 1)

    def test_dump_retry_budget_is_bounded(self):
        call = Mock(side_effect=subprocess.CalledProcessError(124, 'adb'))
        with self.assertRaises(subprocess.CalledProcessError):
            read_ui('test', call=call, pause=Mock())
        self.assertEqual(call.call_count, 3)
