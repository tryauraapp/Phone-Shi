#!/usr/bin/env python3
"""Patch the Android-15 reference radio HAL's compiled-in IMEI in a Magisk overlay."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

SYMBOL = b'_ZN2cf3ril13RefRadioModem7getImeiEi'
STOCK = '867400022047199'
# The compiler folded the constant into MOVZ/MOVK instructions, not .rodata.
MOVES = ((0x28, 0x5286C708, 0, 2), (0x2C, 0x72A686E8, 2, 4),
         (0x3C, 0x52860688, 3, 5), (0x40, 0x72A60608, 5, 7),
         (0x90, 0xD2864648, 7, 9), (0x94, 0xF2A68608, 9, 11),
         (0x9C, 0xF2C626E8, 11, 13), (0xA4, 0xF2E72728, 13, 15))


def function_range(data):
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('Expected an ELF64 AArch64 Android radio library')
    table = struct.unpack_from('<Q', data, 40)[0]
    size, count = struct.unpack_from('<HH', data, 58)
    if size != 64 or table + size * count > len(data):
        raise ValueError('Invalid ELF section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, table + size * i) for i in range(count)]
    matches = []
    for section in sections:
        if section[1] != 11:
            continue
        pool = sections[section[6]]
        strings = data[pool[4]:pool[4] + pool[5]]
        for offset in range(section[4], section[4] + section[5], 24):
            name, info, other, index, address, length = struct.unpack_from('<IBBHQQ', data, offset)
            if strings[name:].split(b'\0', 1)[0] != SYMBOL or index == 0:
                continue
            body = sections[index]
            position = body[4] + address - body[3]
            if not body[2] & 4 or position < body[4] or position + length > body[4] + body[5]:
                raise ValueError('Invalid radio IMEI function bounds')
            matches.append((position, length))
    if len(matches) != 1 or matches[0][1] < 0xA8:
        raise ValueError('Supported reference radio IMEI function not found')
    return matches[0]


def patch(original, imei):
    if not re.fullmatch(r'\d{15}', imei):
        raise ValueError('Expected a 15-digit reserved IMEI')
    position, size = function_range(original)
    patched = bytearray(original)
    for relative, expected, start, end in MOVES:
        offset = position + relative
        instruction = struct.unpack_from('<I', original, offset)[0]
        if instruction != expected:
            raise ValueError('Unsupported radio IMEI instruction layout; patch refused')
        # Preserve opcode, destination register and shift; replace only imm16.
        immediate = int.from_bytes(imei[start:end].encode(), 'little')
        replacement = (instruction & ~(0xFFFF << 5)) | (immediate << 5)
        struct.pack_into('<I', patched, offset, replacement)
    return bytes(patched)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    identity = json.loads(args.identity.read_text())
    original = args.input.read_bytes()
    result = patch(original, identity['imei'])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'patched.so').write_bytes(result)
    report = dict(avd=identity['avd'], original_sha256=hashlib.sha256(original).hexdigest(),
                  patched_sha256=hashlib.sha256(result).hexdigest(), changed_instructions=len(MOVES))
    (args.output_dir / 'patch-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    library = 'system/vendor/lib64/libril-modem-lib.so'
    with zipfile.ZipFile(args.output_dir / 's25_radio_imei.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('module.prop', 'id=s25_radio_imei\nname=S25 per-device radio IMEI\nversion=1\nversionCode=1\nauthor=EMU Lab\ndescription=Reserved synthetic identifier in Android 15 reference radio HAL\n')
        archive.writestr('customize.sh', 'set_perm "$MODPATH/' + library + '" 0 0 0644 u:object_r:vendor_file:s0\n')
        archive.writestr(library, result)
    print('Prepared per-device Android radio IMEI overlay; reboot required.')


if __name__ == '__main__':
    main()
