from pathlib import Path
import tempfile
import unittest

import setup_network as n
import prepare_modem_config as modem


READY = ('Active default network: 100\nCurrent Networks:\n'
         'NetworkAgentInfo{network{100} Capabilities: INTERNET&VALIDATED&NOT_VPN]\n'
         'Status for known UIDs:\n')
OFFLINE = 'Active default network: none\nCurrent Networks:\n'


class NetworkTests(unittest.TestCase):
    def test_validation_requires_current_default_network_capability(self):
        self.assertTrue(n.validated_default(READY))
        self.assertFalse(n.validated_default(OFFLINE))
        self.assertFalse(n.validated_default(READY.replace('INTERNET&VALIDATED', 'INTERNET')))
        self.assertFalse(n.validated_default(READY.replace('network{100}', 'network{101}')))
        self.assertFalse(n.validated_default(READY.replace('INTERNET&VALIDATED', 'INTERNET&NOT_VALIDATED')))

    def test_existing_validated_connection_is_preserved(self):
        calls = []
        n.ensure_network('test', call=lambda *args: calls.append(args) or READY)
        self.assertEqual(calls, [('test', 'shell', 'dumpsys', 'connectivity')])

    def test_recovery_waits_for_validation_and_connects_only_emulator_ap_once(self):
        calls, clock, dumps = [], [0], iter([OFFLINE, OFFLINE, OFFLINE, READY])
        def call(serial, *args):
            calls.append(args)
            if args == ('shell', 'dumpsys', 'connectivity'):
                return next(dumps)
            if args[-1] == 'list-scan-results':
                return '02:15:b2:00:00:01 2437 -50 1.0 AndroidWifi [ESS]\n'
            return ''
        n.ensure_network('test', call=call, now=lambda: clock[0], pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertEqual(calls.count(('shell', 'cmd', 'wifi', 'connect-network', 'AndroidWifi', 'open')), 1)

    def test_recovery_times_out_without_connecting_unrelated_wifi(self):
        calls, clock = [], [0]
        def call(serial, *args):
            calls.append(args)
            return OFFLINE if args[-1] == 'connectivity' else 'CafeWifi [ESS]'
        with self.assertRaisesRegex(RuntimeError, 'no validated internet'):
            n.ensure_network('test', timeout=4, call=call, now=lambda: clock[0],
                             pause=lambda t: clock.__setitem__(0, clock[0] + t))
        self.assertFalse(any('connect-network' in c for c in calls))

    def test_modem_configs_follow_private_ramdisk_and_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sdk/data/misc/modem_simulator'
            source.mkdir(parents=True)
            (source / 'iccprofile_for_sim0.xml').write_text('<sim/>')
            avd = root / 'phone.avd'
            target = modem.prepare(root / 'sdk', avd)
            self.assertEqual(target, avd / 'data/misc/modem_simulator')
            self.assertEqual((target / 'iccprofile_for_sim0.xml').read_text(), '<sim/>')
            modem.prepare(root / 'sdk', avd)  # Idempotent without resetting SIM state.
            (target / 'iccprofile_for_sim0.xml').write_text('<custom/>')
            with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
                modem.prepare(root / 'sdk', avd)
            self.assertEqual((target / 'iccprofile_for_sim0.xml').read_text(), '<custom/>')
