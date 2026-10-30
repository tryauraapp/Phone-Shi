import json
from pathlib import Path
import struct
import tempfile
import unittest

from linux_avd_identity import patch_engine, prepare, reserve
from device_identifiers import STOCK_IMEIS, luhn_digit


def engine():
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', header, 18, 62)
    compiled = (b'\x48\xb8' + b'86740002' + b'\x48\x89\x44\x24\x39\x48\xb8' +
                b'22047199' + b'\x48\x89\x44\x24\x40')
    return bytes(header) + b'---'.join(x + b'\0' for x in STOCK_IMEIS) + b'^[a-zA-Z0-9._-,]+$\0' + compiled


class LinuxIdentityTests(unittest.TestCase):
    def test_registry_is_stable_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'ids.db'
            a = reserve(db, 'a')
            self.assertEqual(a, reserve(db, 'a'))
            rows = [a] + [reserve(db, str(i)) for i in range(30)]
            self.assertEqual(len(rows), len({r['serial'] for r in rows}))
            self.assertEqual(len(rows), len({r['imei'] for r in rows}))
            for row in rows:
                self.assertEqual(luhn_digit(row['imei'][:14]), row['imei'][-1])

    def test_patch_preserves_length_and_rejects_ambiguous_or_wrong_architecture(self):
        original = engine()
        result = patch_engine(original, '004400000000008')
        self.assertEqual(len(original), len(result))
        self.assertEqual(result.count(b'004400000000008\0'), 2)
        self.assertIn(b'^[a-zA-Z0-9._,-]+$\0', result)
        self.assertNotIn(b'^[a-zA-Z0-9._-,]+$\0', result)
        self.assertIn(b'\x48\xb800440000\x48\x89\x44\x24\x39\x48\xb800000008', result)
        for invalid in [original + STOCK_IMEIS[0] + b'\0', original.replace(STOCK_IMEIS[1], b'x' * 15),
                        original.replace(b'\x48\xb8' + b'86740002', b'x' * 10), b'no ELF']:
            with self.assertRaises(ValueError):
                patch_engine(invalid, '004400000000008')
        with self.assertRaises(ValueError):
            patch_engine(original, '004400000000009')

    def test_private_copy_leaves_sdk_unchanged_and_rejects_later_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk = root / 'sdk'
            source = sdk / 'emulator/qemu/linux-x86_64'
            source.mkdir(parents=True)
            (sdk / 'emulator/lib64').mkdir()
            (sdk / 'emulator/emulator').write_bytes(b'launcher')
            avd = root / 'phone.avd'
            avd.mkdir()
            (avd / 'config.ini').write_text('AvdId=phone\n')
            for name in ('qemu-system-x86_64', 'qemu-system-x86_64-headless'):
                (source / name).write_bytes(engine())
            saved = prepare(sdk, avd, 'phone', root / 'ids.db', '0123456789abcdef')
            self.assertEqual(saved, prepare(sdk, avd, 'phone', root / 'ids.db'))
            for name in saved['source_sha256']:
                self.assertEqual((source / name).read_bytes(), engine())
                p = Path(saved['private_emulator']) / 'qemu/linux-x86_64' / name
                self.assertIn(saved['imei'].encode(), p.read_bytes())
            p.write_bytes(b'corrupted')
            with self.assertRaises(ValueError):
                prepare(sdk, avd, 'phone', root / 'ids.db')


if __name__ == '__main__':
    unittest.main()
