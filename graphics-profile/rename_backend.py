#!/usr/bin/env python3
"""Change only the backend SONAME so a same-ABI forwarding wrapper can load it."""
from pathlib import Path
import struct
import sys

original = Path(sys.argv[1]).read_bytes()
if original[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", original, 18)[0] != 183:
    raise SystemExit("Expected an AArch64 ELF64 backend")
offset = struct.unpack_from("<Q", original, 40)[0]
size, count, index = struct.unpack_from("<HHH", original, 58)
names_section = struct.unpack_from("<IIQQQQIIQQ", original, offset+size*index)
names = original[names_section[4]:names_section[4]+names_section[5]]
result = None
for i in range(count):
    entry = struct.unpack_from("<IIQQQQIIQQ", original, offset+size*i)
    if names[entry[0]:].split(b"\0", 1)[0] != b".dynstr":
        continue
    start, length = entry[4], entry[5]
    data = original[start:start+length]
    old = b"libGLESv2_emulation.so\0"
    new = b"libGLESv2_backend.so\0".ljust(len(old), b"\0")
    if data.count(old) != 1 or len(new) != len(old):
        raise SystemExit("Unexpected SONAME layout")
    result = original[:start]+data.replace(old, new)+original[start+length:]
if result is None or len(result) != len(original):
    raise SystemExit("Backend rename failed")
Path(sys.argv[2]).write_bytes(result)
