from pathlib import Path
import tempfile
import json
import unittest
import shutil

import setup_network as n
import prepare_modem_config as modem


READY = ('Active default network: 100\nCurrent Networks:\n'
         'NetworkAgentInfo{network{100} Transports: CELLULAR Capabilities: INTERNET&VALIDATED&NOT_VPN]\n'
         'Status for known UIDs:\n')
OFFLINE = 'Active default network: none\nCurrent Networks:\n'


class NetworkTests(unittest.TestCase):
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
