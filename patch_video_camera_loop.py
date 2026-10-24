#!/usr/bin/env python3
"""Patch a private ARM64 emulator engine so videofile cameras loop at EOF."""
import argparse
import shutil
import struct
import subprocess
from pathlib import Path


UPDATE_SYMBOL = ('__ZN7android3ver18RawVideofileSource11UpdateImageEx'
                 'NSt3__18optionalINS0_13RawImageTokenEEENS2_8functionIFN4absl12lts_202401166StatusE'
                 'PKNS0_18RawImageBufferViewEEEE')
LENGTH_SYMBOL = '__ZN7android3ver18RawVideofileSource20GetAnimationLengthUsEv'
START_SYMBOL = '__ZN7android3ver18RawVideofileSource5StartE14VerImageFormatii'
PROLOGUE = 0xD10343FF  # sub sp, sp, #0xd0
LEGACY_TRAMPOLINE_PREFIX = (
    PROLOGUE,
    0xF9402409,  # ldr x9, [x0, #0x48]  (AVFormatContext)
    0xF9422529,  # ldr x9, [x9, #0x448] (duration, microseconds)
    0xB4000069,  # cbz x9, +12
    0x9AC9082A,  # udiv x10, x1, x9
    0x9B098541,  # msub x1, x10, x9, x1 (requested_time %= duration)
)
CADENCE_TRAMPOLINE_PREFIX = (
    PROLOGUE,
    0xF9401801,  # ldr x1, [x0, #0x30] (previous playback time)
    0x529046A9,  # mov w9, #33333       (30 fps camera cadence)
    0x8B090021,  # add x1, x1, x9
    0xF9402409,  # ldr x9, [x0, #0x48]  (AVFormatContext)
    0xF9422529,  # ldr x9, [x9, #0x448] (duration, microseconds)
    0xB4000069,  # cbz x9, +12
    0x9AC9082A,  # udiv x10, x1, x9
    0x9B098541,  # msub x1, x10, x9, x1 (playback_time %= duration)
)
FAST_TRAMPOLINE_PREFIX = (
    PROLOGUE,
    0xF940180B,  # ldr x11, [x0, #0x30] (previous playback time)
    0x529046A9,  # mov w9, #33333        (30 fps camera cadence)
    0x8B090161,  # add x1, x11, x9
    0xF9402409,  # ldr x9, [x0, #0x48]   (AVFormatContext)
    0xF9422529,  # ldr x9, [x9, #0x448]  (duration, microseconds)
    0xB40000C9,  # cbz x9, +24
    0x9AC9082A,  # udiv x10, x1, x9
    0x9B098541,  # msub x1, x10, x9, x1  (playback_time %= duration)
    0xEB0B003F,  # cmp x1, x11
    0x54000042,  # b.hs +8
    0xF9001C1F,  # str xzr, [x0, #0x38]  (reset decoded PTS after rewind)
)
TRAMPOLINE_PREFIX = FAST_TRAMPOLINE_PREFIX[:2] + (0x52856CE9,) + FAST_TRAMPOLINE_PREFIX[3:]


def macho_layout(data):
    if struct.unpack_from('<II', data) != (0xFEEDFACF, 0x100000C):
        raise RuntimeError('Video loop patch requires a thin ARM64 Mach-O engine')
    ncmds = struct.unpack_from('<I', data, 16)[0]
    offset, segments, text, symtab = 32, [], None, None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, offset)
        if cmd == 0x19:
            segment_name = data[offset + 8:offset + 24].rstrip(b'\0')
            vmaddr, _, fileoff, filesize = struct.unpack_from('<QQQQ', data, offset + 24)
            segments.append((vmaddr, fileoff, filesize))
            nsects = struct.unpack_from('<I', data, offset + 64)[0]
            section_offset = offset + 72
            for index in range(nsects):
                section = section_offset + index * 80
                section_name = data[section:section + 16].rstrip(b'\0')
                section_segment = data[section + 16:section + 32].rstrip(b'\0')
                address, length = struct.unpack_from('<QQ', data, section + 32)
                file_position = struct.unpack_from('<I', data, section + 48)[0]
                if segment_name == b'__TEXT' and section_segment == b'__TEXT' and section_name == b'__text':
                    text = (address, file_position, length)
        elif cmd == 2:
            symtab = struct.unpack_from('<IIII', data, offset + 8)
        offset += size
    if text is None or symtab is None:
        raise RuntimeError('Engine has no __TEXT,__text section or symbol table')
    symoff, nsyms, stroff, strsize = symtab
    symbols = {}
    for index in range(nsyms):
        name_offset, _, _, _, address = struct.unpack_from('<IBBHQ', data, symoff + index * 16)
        if not name_offset or name_offset >= strsize:
            continue
        start = stroff + name_offset
        end = data.find(b'\0', start, stroff + strsize)
        if end >= 0:
            symbols[data[start:end].decode('ascii', errors='replace')] = address
    return segments, text, symbols


def file_offset(address, segments):
    positions = [fileoff + address - vmaddr for vmaddr, fileoff, size in segments
                 if vmaddr <= address < vmaddr + size]
    if len(positions) != 1:
        raise RuntimeError('Invalid Mach-O virtual address')
    return positions[0]


def branch(source, target):
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise RuntimeError('ARM64 branch target is out of range')
    return 0x14000000 | ((delta // 4) & 0x03FFFFFF)


def branch_target(source, instruction):
    immediate = instruction & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 0x04000000
    return source + immediate * 4


def patch_engine(data):
    segments, text, symbols = macho_layout(data)
    if UPDATE_SYMBOL not in symbols or LENGTH_SYMBOL not in symbols:
        raise RuntimeError('Unsupported emulator engine: video camera symbols are missing')
    update_address = symbols[UPDATE_SYMBOL]
    update_offset = file_offset(update_address, segments)
    first = struct.unpack_from('<I', data, update_offset)[0]
    cave_offset = None
    if first & 0xFC000000 == 0x14000000:
        cave_address = branch_target(update_address, first)
        cave_offset = file_offset(cave_address, segments)
        expected = TRAMPOLINE_PREFIX + (branch(cave_address + 48, update_address + 4),)
        if struct.unpack_from('<13I', data, cave_offset) == expected:
            return data, False
        legacy = LEGACY_TRAMPOLINE_PREFIX + (branch(cave_address + 24, update_address + 4),)
        cadence = CADENCE_TRAMPOLINE_PREFIX + (branch(cave_address + 36, update_address + 4),)
        fast = FAST_TRAMPOLINE_PREFIX + (branch(cave_address + 48, update_address + 4),)
        if (struct.unpack_from('<7I', data, cave_offset) != legacy
                and struct.unpack_from('<10I', data, cave_offset) != cadence
                and struct.unpack_from('<13I', data, cave_offset) != fast):
            raise RuntimeError('Unsupported existing video loop patch; patch refused')
    if first != PROLOGUE:
        if cave_offset is None:
            raise RuntimeError('Unsupported video update function layout; patch refused')
    length_offset = file_offset(symbols[LENGTH_SYMBOL], segments)
    expected_length = (0xF9402408, 0xF9422508, 0xD2F00009, 0xEB09011F,
                       0x9A8803E0, 0xD65F03C0)
    if struct.unpack_from('<6I', data, length_offset) != expected_length:
        raise RuntimeError('Unsupported video duration layout; patch refused')

    text_address, text_offset, text_size = text
    if cave_offset is None:
        for candidate in range(text_offset, text_offset + text_size - 51, 4):
            if data[candidate:candidate + 52] == b'\0' * 52:
                cave_offset = candidate
                break
    if cave_offset is None:
        raise RuntimeError('No safe executable padding is available for the video loop patch')
    cave_address = text_address + cave_offset - text_offset
    trampoline = TRAMPOLINE_PREFIX + (branch(cave_address + 48, update_address + 4),)
    output = bytearray(data)
    struct.pack_into('<I', output, update_offset, branch(update_address, cave_address))
    struct.pack_into('<13I', output, cave_offset, *trampoline)
    return bytes(output), True


def patch_nonseekable_start(data):
    """Allow the videofile decoder to start on a continuously-fed named pipe."""
    segments, _, symbols = macho_layout(data)
    if START_SYMBOL not in symbols:
        raise RuntimeError('Unsupported emulator engine: video start symbol is missing')
    position = file_offset(symbols[START_SYMBOL], segments) + 0x3C
    instruction = struct.unpack_from('<I', data, position)[0]
    if instruction == 0xD503201F:  # nop; already patched
        return data, False
    if instruction != 0x37F804A0:  # tbnz w0, #31, seek_error
        raise RuntimeError('Unsupported video start function layout; pipe patch refused')
    output = bytearray(data)
    struct.pack_into('<I', output, position, 0xD503201F)
    return bytes(output), True


def patch_file(path):
    original = path.read_bytes()
    patched, loop_changed = patch_engine(original)
    patched, pipe_changed = patch_nonseekable_start(patched)
    changed = loop_changed or pipe_changed
    if not changed:
        return False
    backup = path.with_name(path.name + '.pre-video-loop')
    if not backup.exists():
        shutil.copy2(path, backup)
    staged = path.with_name(path.name + '.video-loop-new')
    try:
        staged.write_bytes(patched)
        staged.chmod(path.stat().st_mode)
        subprocess.run(['codesign', '--force', '--sign', '-', '--preserve-metadata=entitlements', str(staged)],
                       check=True, capture_output=True, text=True)
        subprocess.run(['codesign', '--verify', str(staged)], check=True, capture_output=True, text=True)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd-dir', type=Path, required=True)
    args = parser.parse_args()
    engine_dir = args.avd_dir.expanduser().resolve() / 's25-emulator/qemu/darwin-aarch64'
    changed = []
    for name in ('qemu-system-aarch64', 'qemu-system-aarch64-headless'):
        target = engine_dir / name
        if patch_file(target):
            changed.append(name)
    print('Patched: ' + ', '.join(changed) if changed else 'Video loop patch already applied.')


if __name__ == '__main__':
    main()
