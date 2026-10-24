import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from setup_su import PACKAGE, ShellSetup, shell_toggle


class ShellSetupTests(unittest.TestCase):
    def result(self, code=0, out=b'', err=b''):
        return subprocess.CompletedProcess([], code, out, err)

    def test_request_has_device_and_host_timeouts_and_distinct_results(self):
        for result, expected in [(self.result(out=b'0\r\n'), 'allowed'),
                                 (self.result(1, err=b'Permission denied'), 'denied'),
                                 (self.result(13, err=b'Permission denied'), 'denied'),
                                 (self.result(124), 'timed_out')]:
            with self.subTest(expected=expected):
                run = Mock(side_effect=[self.result(out=b'test-avd\n'), result])
                setup = ShellSetup('test', 'test-avd', '.', run=run)
                self.assertEqual(setup.probe(), expected)
                args, kwargs = run.call_args
                self.assertIn('timeout 35 su -c "id -u"', args[0])
                self.assertLessEqual(kwargs['timeout'], 38)

    def test_host_timeout_and_disconnect_are_not_denials(self):
        for failure in [subprocess.TimeoutExpired('adb', 38),
                        self.result(1, err=b"adb: device 'test' not found")]:
            run = Mock(side_effect=[self.result(out=b'avd'), failure])
            setup = ShellSetup('test', 'avd', '.', run=run)
            if isinstance(failure, Exception):
                self.assertEqual(setup.probe(), 'timed_out')
            else:
                with self.assertRaises(ConnectionError):
                    setup.probe()

    def test_identity_mismatch_never_requests_root(self):
        run = Mock(return_value=self.result(out=b'another-avd'))
        with self.assertRaises(ConnectionError):
            ShellSetup('test', 'avd', '.', run=run).probe()
        self.assertEqual(run.call_count, 1)

    def test_one_recovery_only_and_no_policy_tapping_on_timeout(self):
        setup = ShellSetup('test', 'avd', '.')
        setup.open_manager = Mock()
        setup.probe = Mock(return_value='timed_out')
        setup.diagnostics = Mock()
        setup.checked = Mock()
        setup.enable_shell = Mock()
        with self.assertRaisesRegex(RuntimeError, 'still time out'):
            setup.complete()
        self.assertEqual(setup.probe.call_count, 2)
        self.assertEqual(setup.diagnostics.call_count, 2)
        setup.checked.assert_called_once_with('shell', 'am', 'force-stop', PACKAGE)
        setup.enable_shell.assert_not_called()

    def test_denied_request_requires_fresh_success_after_policy_change(self):
        setup = ShellSetup('test', 'avd', '.')
        setup.open_manager = Mock()
        setup.probe = Mock(side_effect=['denied', 'allowed'])
        setup.enable_shell = Mock()
        setup.complete()
        setup.enable_shell.assert_called_once()
        self.assertEqual(setup.probe.call_count, 2)

    def test_deadline_prevents_command_and_diagnostics_survive_errors(self):
        run = Mock(side_effect=subprocess.TimeoutExpired('adb', 10))
        with tempfile.TemporaryDirectory() as folder:
            setup = ShellSetup('test', 'avd', folder, timeout=0, run=run)
            with self.assertRaises(TimeoutError):
                setup.command('shell', 'id')
            run.assert_not_called()
            setup.diagnostics('timed_out', 1)
            self.assertTrue((Path(folder) / 'attempt-1/status.json').exists())
            self.assertEqual(run.call_count, 4)
            self.assertTrue(all(call.kwargs['timeout'] == 10 for call in run.call_args_list))

    def test_structured_shell_row_ignores_unrelated_switch(self):
        label = f'<node package="{PACKAGE}" text="Shell" bounds="[0,0][100,50]"/>'
        switch = f'<node package="{PACKAGE}" class="android.widget.Switch" enabled="true" checked="false" bounds="[100,0][200,50]"/>'
        self.assertEqual(shell_toggle(f'<hierarchy><node>{label}{switch}</node></hierarchy>'), ((150, 25), False))
        self.assertIsNone(shell_toggle(f'<hierarchy><node>{label}</node><node>{switch.replace("[100,0][200,50]", "[100,500][200,550]")}</node></hierarchy>'))


if __name__ == '__main__':
    unittest.main()
