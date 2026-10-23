import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import struct
from types import SimpleNamespace
from unittest.mock import patch

import device_identifiers as identifiers
import emulator_proxy


class IdentifierTests(unittest.TestCase):
    def test_disabled_absent_wifi_is_optional_and_root_scripts_use_stdin(self):
        identity = dict(avd='Test', serial='S25TEST', imei='004400000000008', android_id='0123456789abcdef',
                        cellular_mac='06:11:22:33:44:55', wifi_mac='02:11:22:33:44:55',
                        network={'radio_subnet': '10.12.14.0/24'},
                        system_settings={'screen_off_timeout': '30000'})
        data = b'\0' * 4 + (15).to_bytes(4, 'little') + identity['imei'].encode('utf-16-le') + b'\0\0'
        parcel = '0x00000000: ' + ' '.join(f'{int.from_bytes(data[i:i+4], "little"):08x}' for i in range(0, len(data), 4))
        roots = []
        def run(command, **kwargs):
            if command[-1] == 'su':
                script = kwargs['input']
                roots.append(script)
                if 'service call' in script:
                    output = parcel
                elif 'eth0/address' in script:
                    output = identity['cellular_mac']
                else:
                    output = ''  # Disabled Wi-Fi has no wlan0 interface.
            elif command[-1] == 'name':
                output = 'Test\nOK'
            elif command[-1] == 'ro.serialno':
                output = identity['serial']
            elif command[-1] == 'android_id':
                output = identity['android_id']
            elif command[-1] == 'screen_off_timeout':
                output = '2147483647'
            else:
                output = '15: eth0 inet 10.12.14.100/24 scope global eth0'
            return SimpleNamespace(stdout=output)
        with patch.object(identifiers.subprocess, 'run', side_effect=run):
            actual = identifiers.verify('adb', 'emulator-5554', identity)
        self.assertEqual(actual['imei'], identity['imei'])
        self.assertNotIn('wifi_mac', actual)
        self.assertEqual(actual['settings_drift']['screen_off_timeout'],
                         {'expected': '30000', 'actual': '2147483647'})
        self.assertTrue(any('wlan0' in script and 'exit 0' in script for script in roots))

    def test_modem_function_patch_is_bounded_and_rejects_unknown_layout(self):
        # Minimal ARM64 Mach-O with the three exported modem functions.
        data = bytearray(1024)
        struct.pack_into('<IIIIIIII', data, 0, 0xFEEDFACF, 0x100000C, 0, 2, 2, 96, 0, 0)
        struct.pack_into('<II16sQQQQiiII', data, 32, 0x19, 72, b'__TEXT',
                         0x100000000, 1024, 0, 1024, 7, 5, 0, 0)
        struct.pack_into('<IIIIII', data, 104, 2, 24, 700, 3, 760, 250)
        strings = bytearray(b'\0')
        slots = [('address', 200, 44, 12), ('gateway', 244, 36, 8), ('dns', 280, 36, 8)]
        for index, (key, offset, capacity, length) in enumerate(slots):
            name_offset = len(strings)
            strings.extend(identifiers.NETWORK_SYMBOLS[key].encode() + b'\0')
            struct.pack_into('<IBBHQ', data, 700 + 16 * index, name_offset, 0xF, 1, 0, 0x100000000 + offset)
            struct.pack_into('<II', data, offset, 0x52800009 | (length << 5), 0x39005D09)
            struct.pack_into('<I', data, offset + capacity - 4, 0xD65F03C0)
        data[760:760 + len(strings)] = strings
        network = identifiers.network_profile('10.254.254.0/23')
        patched = identifiers.patch_network_engine(bytes(data), network)
        self.assertEqual(len(patched), len(data))
        self.assertEqual(patched[:200], data[:200])
        self.assertEqual(patched[316:], data[316:])
        for key, offset, capacity, length in slots:
            string_length_instruction = struct.unpack_from('<I', patched, offset + (16 if capacity == 44 else 8))[0]
            expected = network['radio_ip'] + '/24' if key == 'address' else '10.254.254.' + ('2' if key == 'gateway' else '3')
            self.assertEqual((string_length_instruction >> 5) & 0xFFFF, len(expected))
        data[200:204] = b'bad!'
        with self.assertRaisesRegex(RuntimeError, 'Unsupported modem function layout'):
            identifiers.patch_network_engine(bytes(data), network)

    def test_existing_registry_is_migrated_without_changing_reserved_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / 'registry.sqlite3'
            with closing(sqlite3.connect(registry)) as db, db:
                db.execute('CREATE TABLE devices (avd TEXT, serial TEXT UNIQUE, imei TEXT UNIQUE, android_id TEXT UNIQUE)')
                db.execute('INSERT INTO devices VALUES (?, ?, ?, ?)', ('Old', 'OLD_SERIAL', '004400000000008', '0123456789abcdef'))
            device = identifiers.reserve(registry, 'New')
            with closing(sqlite3.connect(registry)) as db:
                old = db.execute('SELECT serial, imei, android_id FROM devices WHERE avd=?', ('Old',)).fetchone()
                self.assertEqual(old, ('OLD_SERIAL', '004400000000008', '0123456789abcdef'))
            network = identifiers.network_profile(device['network_cidr'])
            import ipaddress
            radio = ipaddress.ip_network(network['radio_subnet'])
            wifi = ipaddress.ip_network(network['wifi_subnet'])
            self.assertFalse(radio.overlaps(wifi))
            self.assertIn(ipaddress.ip_address(network['radio_ip']), radio)
            for field in ('wifi_mac', 'cellular_mac'):
                first = int(device[field].split(':')[0], 16)
                self.assertEqual(first & 3, 2)  # locally administered, unicast

    def test_registry_reserves_distinct_values_and_database_enforces_uniqueness(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / 'identifiers.sqlite3'
            devices = [identifiers.reserve(registry, f'Test{i}') for i in range(100)]
            for key in ('serial', 'imei', 'android_id', 'wifi_mac', 'cellular_mac', 'network_cidr'):
                self.assertEqual(len({d[key] for d in devices}), 100)
            for device in devices:
                self.assertEqual(len(device['imei']), 15)
                self.assertEqual(identifiers.luhn_digit(device['imei'][:14]), device['imei'][-1])
                self.assertEqual(len(device['android_id']), 16)
            with closing(sqlite3.connect(registry)) as db, db:
                with self.assertRaises(sqlite3.IntegrityError):
                    d = devices[0]
                    db.execute('INSERT INTO devices (avd, serial, imei, android_id) VALUES (?, ?, ?, ?)',
                               ('Duplicate', d['serial'], d['imei'], d['android_id']))

    def test_engine_patch_preserves_size_and_fails_on_unknown_layout(self):
        original = b'prefix' + b'\0'.join(identifiers.STOCK_IMEIS) + b'\0suffix'
        patched = identifiers.patch_engine(original, '004400000000008')
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched.count(b'004400000000008\0'), 2)
        for stock in identifiers.STOCK_IMEIS:
            self.assertNotIn(stock, patched)
        for data in (b'unknown engine', original + original):
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                identifiers.patch_engine(data, '004400000000008')

    def test_prepare_is_private_stable_and_reused_by_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sdk/emulator'
            engines = source / 'qemu/darwin-aarch64'
            engines.mkdir(parents=True)
            (source / 'emulator').write_bytes(b'launcher')
            (source / 'lib64').mkdir()
            original = b'prefix' + b'\0'.join(identifiers.STOCK_IMEIS) + b'\0suffix'
            for name in ('qemu-system-aarch64', 'qemu-system-aarch64-headless'):
                (engines / name).write_bytes(original)
            avd_home = root / 'avds'
            avd = avd_home / 'Test.avd'
            avd.mkdir(parents=True)
            with patch.object(identifiers.subprocess, 'run'), \
                 patch.object(identifiers, 'patch_network_engine', side_effect=lambda data, network: data):
                device = identifiers.prepare(root / 'sdk', avd, 'Test', root / 'registry')
                with self.assertRaisesRegex(RuntimeError, 'refusing to regenerate'):
                    identifiers.prepare(root / 'sdk', avd, 'Test', root / 'registry')
            self.assertEqual((engines / 'qemu-system-aarch64').read_bytes(), original)
            self.assertEqual(json.loads((avd / 's25-identifiers.json').read_text()), device)
            options = emulator_proxy.identifier_options('Test', {'ANDROID_AVD_HOME': str(avd_home)})
            self.assertEqual(options[:4], ['-qemu-top-dir', device['private_emulator'],
                                          '-android-serialno', device['serial']])
            self.assertIn(device['network']['radio_options'], options)

    def test_parcel_imei_and_identifier_mismatch_detection(self):
        imei = '004400000000008'
        data = b'\0' * 4 + len(imei).to_bytes(4, 'little') + imei.encode('utf-16-le') + b'\0\0'
        words = [f'{int.from_bytes(data[i:i+4], "little"):08x}' for i in range(0, len(data), 4)]
        parcel = 'Result: Parcel(\n0x00000000: ' + ' '.join(words) + " 'display text')"
        self.assertEqual(identifiers.parcel_imei(parcel), imei)
        identity = dict(avd='Test', serial='S25ABC', android_id='0123456789abcdef', imei=imei)
        with patch.object(identifiers.subprocess, 'run') as call:
            call.side_effect = [type('Result', (), {'stdout': value}) for value in
                                ('Test\nOK', 'wrong_serial', identity['android_id'], parcel)]
            with self.assertRaisesRegex(RuntimeError, 'serial read-back'):
                identifiers.verify('adb', 'emulator-5554', identity)
        with self.assertRaisesRegex(RuntimeError, 'Could not read modem IMEI'):
            identifiers.parcel_imei('Permission denied')
