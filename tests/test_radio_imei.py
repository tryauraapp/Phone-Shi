import struct
import unittest

import patch_radio_imei as radio


def library():
    data = bytearray(0x600)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, 183)
    struct.pack_into('<Q', data, 40, 0x500)
    struct.pack_into('<HHH', data, 58, 64, 4, 2)
    strings = b'\0' + radio.SYMBOL + b'\0'
    data[0x100:0x100 + len(strings)] = strings
    sections = [(0,) * 10,
                (0, 1, 6, 0x1200, 0x200, 0x200, 0, 0, 4, 0),
                (0, 3, 0, 0, 0x100, len(strings), 0, 0, 1, 0),
                (0, 11, 0, 0, 0x180, 24, 2, 0, 8, 24)]
    for index, section in enumerate(sections):
        struct.pack_into('<IIQQQQIIQQ', data, 0x500 + 64 * index, *section)
    struct.pack_into('<IBBHQQ', data, 0x180, 1, 0x12, 0, 1, 0x1200, 368)
    for relative, instruction, start, end in radio.MOVES:
        struct.pack_into('<I', data, 0x200 + relative, instruction)
    return bytes(data)


class RadioIMEITests(unittest.TestCase):
    def test_reserved_imei_replaces_only_compiled_immediate_fields(self):
        original = library()
        expected = '004459535246007'
        patched = radio.patch(original, expected)
        self.assertEqual(len(original), len(patched))
        decoded = bytearray(15)
        allowed = set()
        for relative, instruction, start, end in radio.MOVES:
            offset = 0x200 + relative
            changed = struct.unpack_from('<I', patched, offset)[0]
            self.assertEqual(changed & ~(0xFFFF << 5), instruction & ~(0xFFFF << 5))
            decoded[start:end] = ((changed >> 5) & 0xFFFF).to_bytes(2, 'little')
            allowed.update(range(offset, offset + 4))
        self.assertEqual(decoded.decode(), expected)
        self.assertTrue(all(a == b or index in allowed for index, (a, b) in enumerate(zip(original, patched))))

    def test_unknown_radio_layout_is_rejected(self):
        original = bytearray(library())
        original[0x228:0x22C] = b'bad!'
        with self.assertRaisesRegex(ValueError, 'instruction layout'):
            radio.patch(bytes(original), '004459535246007')
        with self.assertRaisesRegex(ValueError, '15-digit'):
            radio.patch(library(), 'invalid')
