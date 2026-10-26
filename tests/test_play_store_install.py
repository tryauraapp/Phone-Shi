import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import play_store_install as store


def listing(label, enabled='true'):
    return ('<hierarchy><node text="Bumble Dating App: Meet &amp; Date"/>'
            f'<node text="{label}" enabled="{enabled}" clickable="true" bounds="[0,0][100,100]">'
            f'<node text="{label}" enabled="true" clickable="false" bounds="[10,10][90,90]"/>'
            '</node></hierarchy>')


class PlayStoreTests(unittest.TestCase):
    def test_crash_after_install_request_reopens_and_retries_install(self):
        home = '<hierarchy><node package="com.android.launcher3"/></hierarchy>'
        commands = []
        checks = iter(['', '', '', 'package:com.bumble.app'])

        def run(command, **kwargs):
            commands.append(command)
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                output = ('package:com.bumble.app installer=com.android.vending'
                          if '-i' in args else next(checks))
            return subprocess.CompletedProcess(command, 0, output, '')

        with patch('sys.argv', ['play_store_install.py', '--serial', 'test', '--install-only']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', side_effect=[listing('Install'), home, listing('Install'), listing('Open')]), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        self.assertEqual(sum('market://details?id=com.bumble.app' in c for c in commands), 2)
        self.assertEqual(sum(c[3:6] == ['shell', 'input', 'tap'] for c in commands), 2)
        self.assertIn(['adb', '-s', 'test', 'shell', 'am', 'force-stop', 'com.bumble.app'], commands)

    def test_pof_targets_official_package(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                output = ('package:com.pof.android installer=com.android.vending\n'
                          if '-i' in args else 'package:com.pof.android\n')
            elif args[:3] == ['shell', 'dumpsys', 'package']:
                output = ' versionName=5.19.0\n'
            elif args[:3] == ['shell', 'dumpsys', 'activity']:
                output = 'topResumedActivity: com.pof.android/.MainActivity'
            return subprocess.CompletedProcess(command, 0, output, '')

        screen = listing('Open').replace('Bumble Dating App', 'Plenty of Fish')
        with patch('sys.argv', ['play_store_install.py', '--serial', 'test', '--app', 'pof']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', return_value=screen), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        self.assertTrue(any('market://details?id=com.pof.android' in command for command in commands))

    def test_tinder_targets_correct_package_and_recognizes_first_launch_permission(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                output = 'package:com.tinder' + (' installer=com.android.vending' if '-i' in args else '')
            elif args[:3] == ['shell', 'dumpsys', 'package']:
                output = ' versionName=17.39.0\n'
            elif args[:3] == ['shell', 'dumpsys', 'activity']:
                output = 'topResumedActivity: com.google.android.permissioncontroller/.GrantPermissionsActivity'
            return subprocess.CompletedProcess(command, 0, output, '')
        screens = [listing('Open').replace('Bumble Dating App', 'Tinder'),
                   '<hierarchy><node text="Allow Tinder to send you notifications?"/></hierarchy>']
        with patch('sys.argv', ['play_store_install.py', '--serial', 'test', '--app', 'tinder']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', side_effect=screens), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        self.assertTrue(any('market://details?id=com.tinder' in command for command in commands))
        self.assertNotIn('com.bumble.app', repr(commands))

    def test_account_review_and_play_pass_then_verified_open(self):
        fixture = Path(__file__).parent / 'fixtures/google-play'
        screens = [(fixture / name).read_text() for name in
                   ('google-terms.xml', 'complete-account-setup.xml', 'play-pass-offer.xml')]
        taps = []
        def run(command, **kwargs):
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                output = ('package:com.bumble.app installer=com.android.vending\n'
                          if '-i' in args else 'package:com.bumble.app\n')
            elif args == ['shell', 'dumpsys', 'package', store.PACKAGE]:
                output = ' versionName=5.489.0\n'
            elif args == ['shell', 'dumpsys', 'activity', 'activities']:
                output = 'topResumedActivity: com.bumble.app/.MainActivity'
            elif args[:3] == ['shell', 'input', 'tap']:
                taps.append(tuple(map(int, args[3:])))
            return subprocess.CompletedProcess(command, 0, output, '')
        with patch('sys.argv', ['play_store_install.py', '--serial', 'test']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', side_effect=screens + [listing('Open')]), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        self.assertEqual(taps, [store.button_center(screens[0], 'I agree'),
                                store.button_center(screens[1], 'Continue'),
                                store.button_center(screens[2], 'Not now'), (50, 50)])
        self.assertNotIn(store.button_center(screens[2], 'Check it out'), taps)

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

    def test_install_only_verifies_installer_and_never_taps_open(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            args = command[3:]
            output = ''
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                output = ('package:com.bumble.app installer=com.android.vending\n'
                          if '-i' in args else 'package:com.bumble.app\n')
            elif args[:3] == ['shell', 'dumpsys', 'package']:
                output = ' versionName=5.489.0\n'
            return subprocess.CompletedProcess(command, 0, output, '')

        with patch('sys.argv', ['play_store_install.py', '--serial', 'test', '--install-only']), \
                patch.object(store.subprocess, 'run', side_effect=run), \
                patch.object(store, 'read_ui', return_value=listing('Open')), \
                patch.object(store.time, 'sleep'):
            self.assertEqual(store.main(), 0)
        shell_commands = [command[3:] for command in commands]
        self.assertIn(['shell', 'am', 'force-stop', store.PACKAGE], shell_commands)
        self.assertFalse(any(args[:3] == ['shell', 'input', 'tap'] for args in shell_commands))


if __name__ == '__main__':
    unittest.main()
