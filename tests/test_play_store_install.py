import subprocess
import unittest
from unittest.mock import patch

import play_store_install as store


def listing(label, enabled='true'):
    return ('<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/>'
            f'<node text="{label}" enabled="{enabled}" clickable="true" bounds="[0,0][100,100]">'
            f'<node text="{label}" enabled="true" clickable="false" bounds="[10,10][90,90]"/>'
            '</node></hierarchy>')


class PlayStoreTests(unittest.TestCase):
    def test_disabled_open_control_is_not_actionable(self):
        self.assertIsNone(store.button_center(listing('Open', 'false'), 'Open'))

    def test_nested_label_targets_one_parent_control(self):
        self.assertEqual(store.button_center(listing('Install'), 'Install'), (50, 50))

    def test_open_waits_for_package_commit_and_verifies_play_installer(self):
        package_checks = iter(['', '', 'package:com.bumble.app\n'])
        events = []

        def run(command, **kwargs):
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                if '-i' in args:
                    output = 'package:com.bumble.app installer=com.android.vending\n'
                    events.append('verified-installer')
                else:
                    output = next(package_checks)
                    events.append('installed' if output else 'not-installed')
            elif args == ['shell', 'dumpsys', 'package', store.PACKAGE]:
                output = ' versionName=5.489.0\n'
            elif args == ['shell', 'dumpsys', 'activity', 'activities']:
                output = 'mResumedActivity: ActivityRecord{ com.bumble.app/.MainActivity }'
            elif args[:3] == ['shell', 'input', 'tap']:
                events.append('tap')
            return subprocess.CompletedProcess(command, 0, output, '')

        with patch('sys.argv', ['play_store_install.py', '--serial', 'emulator-test']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', side_effect=[listing('Install'), listing('Open'), listing('Open')]), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        self.assertEqual(events, ['not-installed', 'tap', 'not-installed', 'installed', 'verified-installer', 'tap'])


if __name__ == '__main__':
    unittest.main()
