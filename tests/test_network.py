from pathlib import Path
import tempfile
import json
import unittest
import shutil
import subprocess
from unittest.mock import Mock, patch

import setup_network as n
import prepare_modem_config as modem


READY = ('Active default network: 100\nCurrent Networks:\n'
         'NetworkAgentInfo{network{100} Transports: CELLULAR Capabilities: INTERNET&VALIDATED&NOT_VPN]\n'
         'Status for known UIDs:\n')
OFFLINE = 'Active default network: none\nCurrent Networks:\n'


class NetworkTests(unittest.TestCase):
    def isolation_call(self, sim='', radio='radioService[0]->mRadioIndication == NULL'):
        def call(serial, *args):
            if args == ('emu', 'avd', 'name'):
                return 'test-avd\nOK'
            if args == ('shell', 'getprop', 'gsm.sim.state'):
                return sim
            if args == ('shell', 'su', '-c', 'logcat -b radio -d -t 200'):
                return radio
            return ''
        return Mock(side_effect=call)

    def test_isolation_callback_failure_restarts_radio_once_then_validates(self):
        call = self.isolation_call()
        with patch.object(n, 'ensure_network', side_effect=[RuntimeError('offline'), None]) as ensure:
            n.ensure_isolation_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(call.call_args_list.count(unittest.mock.call(
            'test', 'shell', 'su', '-c', 'setprop ctl.restart vendor.ril-daemon')), 1)
        self.assertFalse(any('reboot' in c.args for c in call.call_args_list))

    def test_isolation_healthy_network_does_not_read_logs_or_restart(self):
        call = self.isolation_call()
        with patch.object(n, 'ensure_network') as ensure:
            n.ensure_isolation_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 1)
        call.assert_called_once_with('test', 'emu', 'avd', 'name')

    def test_isolation_other_network_failures_never_restart_radio(self):
        for sim, radio in [('LOADED', 'mRadioIndication == NULL'), ('', 'No callback errors')]:
            with self.subTest(sim=sim, radio=radio):
                call = self.isolation_call(sim, radio)
                with patch.object(n, 'ensure_network', side_effect=RuntimeError('no validated LTE')) as ensure:
                    with self.assertRaisesRegex(RuntimeError, 'no validated LTE'):
                        n.ensure_isolation_network('test', 'test-avd', call=call)
                self.assertEqual(ensure.call_count, 1)
                self.assertFalse(any('setprop ctl.restart vendor.ril-daemon' in c.args for c in call.call_args_list))

    def test_isolation_repeated_failure_stops_after_one_restart(self):
        call = self.isolation_call()
        with patch.object(n, 'ensure_network', side_effect=RuntimeError('no validated LTE')) as ensure:
            with self.assertRaisesRegex(RuntimeError, 'no validated LTE'):
                n.ensure_isolation_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(call.call_args_list.count(unittest.mock.call(
            'test', 'shell', 'su', '-c', 'setprop ctl.restart vendor.ril-daemon')), 1)

    def test_isolation_recovery_rejects_another_device_before_changes(self):
        call = Mock(return_value='other-avd\nOK')
        with patch.object(n, 'ensure_network') as ensure:
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                n.ensure_isolation_network('test', 'test-avd', call=call)
        ensure.assert_not_called()

    def recovery_call(self, boot='new'):
        boots = iter(['old'])
        def call(serial, *args):
            if args == ('emu', 'avd', 'name'):
                return 'test-avd\nOK'
            if args == ('shell', 'cat', '/proc/sys/kernel/random/boot_id'):
                return next(boots, boot)
            if args == ('shell', 'getprop', 'sys.boot_completed'):
                return '1'
            if args == ('shell', 'dumpsys', 'connectivity'):
                return OFFLINE
            return ''
        return Mock(side_effect=call)

    def test_first_boot_success_never_reboots(self):
        call = self.recovery_call()
        with patch.object(n, 'ensure_network') as ensure:
            n.ensure_first_boot_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 1)
        call.assert_called_once_with('test', 'emu', 'avd', 'name')

    def test_first_boot_retries_network_after_confirmed_new_boot(self):
        call = self.recovery_call()
        with patch.object(n, 'ensure_network', side_effect=[RuntimeError('offline'), None]) as ensure:
            n.ensure_first_boot_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(call.call_args_list.count(unittest.mock.call('test', 'reboot')), 1)

    def test_persistent_network_failure_does_not_reboot_twice(self):
        call = self.recovery_call()
        with patch.object(n, 'ensure_network', side_effect=RuntimeError('no validated LTE')) as ensure:
            with self.assertRaisesRegex(RuntimeError, 'no validated LTE'):
                n.ensure_first_boot_network('test', 'test-avd', call=call)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(call.call_args_list.count(unittest.mock.call('test', 'reboot')), 1)

    def test_network_recovery_rejects_another_phone(self):
        call = Mock(return_value='other-avd\nOK')
        with patch.object(n, 'ensure_network') as ensure:
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                n.ensure_first_boot_network('test', 'test-avd', call=call)
        ensure.assert_not_called()
        call.assert_called_once_with('test', 'emu', 'avd', 'name')

    def test_recovery_never_accepts_stale_boot_complete_flag(self):
        call, clock = self.recovery_call(boot='old'), [0]
        with patch.object(n, 'ensure_network', side_effect=RuntimeError('offline')) as ensure:
            with self.assertRaisesRegex(RuntimeError, 'reboot did not finish'):
                n.ensure_first_boot_network('test', 'test-avd', boot_timeout=4, call=call,
                    now=lambda: clock[0], pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertEqual(ensure.call_count, 1)

    def test_recovery_reconnects_only_selected_offline_transport(self):
        clock, boot_reads = [0], [0]
        base = self.recovery_call()
        def call(serial, *args):
            if args == ('shell', 'cat', '/proc/sys/kernel/random/boot_id'):
                boot_reads[0] += 1
                if boot_reads[0] == 1:
                    return 'old'
                if clock[0] < 22:
                    raise subprocess.CalledProcessError(1, 'adb')
                return 'new'
            return base(serial, *args)
        with patch.object(n, 'ensure_network', side_effect=[RuntimeError('offline'), None]) as ensure:
            n.ensure_first_boot_network('test', 'test-avd', call=call,
                now=lambda: clock[0], pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertEqual(ensure.call_count, 2)
        self.assertIn(unittest.mock.call('test', 'reconnect'), base.call_args_list)
        self.assertFalse(any('kill-server' in c.args or 'start-server' in c.args for c in base.call_args_list))

    def test_validation_requires_current_default_network_capability(self):
        self.assertTrue(n.validated_default(READY))
        self.assertFalse(n.validated_default(OFFLINE))
        self.assertFalse(n.validated_default(READY.replace('INTERNET&VALIDATED', 'INTERNET')))
        self.assertFalse(n.validated_default(READY.replace('network{100}', 'network{101}')))
        self.assertFalse(n.validated_default(READY.replace('INTERNET&VALIDATED', 'INTERNET&NOT_VALIDATED')))

    def test_existing_cellular_lte_connection_is_verified_and_wifi_disabled(self):
        calls = []
        def call(*args):
            calls.append(args)
            if args[-1] == 'connectivity':
                return READY
            if args[-1] == 'telephony.registry':
                return 'mDataConnectionNetworkType=13'
            return 'completed'
        n.ensure_network('test', call=call)
        self.assertIn(('test', 'shell', 'svc', 'wifi', 'disable'), calls)
        self.assertNotIn(('test', 'shell', 'svc', 'wifi', 'enable'), calls)
        self.assertIn(('test', 'shell', 'dumpsys', 'telephony.registry'), calls)

    def test_recovery_waits_for_cellular_validation_and_lte_registration(self):
        calls, clock, dumps = [], [0], iter([OFFLINE, OFFLINE, OFFLINE, READY])
        def call(serial, *args):
            calls.append(args)
            if args == ('shell', 'dumpsys', 'connectivity'):
                return next(dumps)
            if args[-1] == 'telephony.registry':
                return 'mDataConnectionNetworkType=LTE'
            return 'completed'
        n.ensure_network('test', call=call, now=lambda: clock[0], pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertEqual(calls.count(('shell', 'cmd', 'phone', 'set-allowed-network-types-for-users', '-s', '0', '1000000000000')), 1)
        self.assertNotIn(('shell', 'svc', 'wifi', 'enable'), calls)

    def test_recovery_times_out_without_falling_back_to_wifi(self):
        calls, clock = [], [0]
        def call(serial, *args):
            calls.append(args)
            return OFFLINE if args[-1] == 'connectivity' else 'completed'
        with self.assertRaisesRegex(RuntimeError, 'no validated LTE'):
            n.ensure_network('test', timeout=4, call=call, now=lambda: clock[0],
                             pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertFalse(any('connect-network' in c for c in calls))

    def test_wifi_default_or_non_lte_network_is_not_accepted(self):
        self.assertTrue(n.validated_default(READY, 'CELLULAR'))
        self.assertFalse(n.validated_default(READY.replace('CELLULAR', 'WIFI'), 'CELLULAR'))
        self.assertFalse(n.lte_registered('mDataConnectionNetworkType=20'))
        self.assertFalse(n.lte_registered('mDataConnectionNetworkType=3'))
        self.assertTrue(n.lte_registered('mRilDataRadioTechnology=14(LTE)'))

    def test_modem_configs_follow_private_ramdisk_and_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sdk/data/misc/modem_simulator'
            source.mkdir(parents=True)
            (source / 'iccprofile_for_sim0.xml').write_text('<sim/>')
            avd = root / 'phone.avd'
            target = modem.prepare(root / 'sdk', avd)
            self.assertEqual(target, avd / 's25-system/data/misc/modem_simulator')
            self.assertEqual((target / 'iccprofile_for_sim0.xml').read_text(), '<sim/>')
            modem.prepare(root / 'sdk', avd, lte_only=True)
            nvram = json.loads((target / 'modem_nvram.json').read_text())
            self.assertEqual(nvram['instances']['0']['modem_technoloy'], 32)
            self.assertEqual(nvram['instances']['0']['preferred_network_mode'], 32)
            # Emulator initialization clears AVD/data on the first boot.
            (avd / 'data/misc').mkdir(parents=True)
            shutil.rmtree(avd / 'data')
            self.assertTrue((target / 'iccprofile_for_sim0.xml').is_file())
            self.assertTrue((target / 'modem_nvram.json').is_file())
            modem.prepare(root / 'sdk', avd)  # Idempotent without resetting SIM state.
            (target / 'iccprofile_for_sim0.xml').write_text('<custom/>')
            with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
                modem.prepare(root / 'sdk', avd)
            self.assertEqual((target / 'iccprofile_for_sim0.xml').read_text(), '<custom/>')
