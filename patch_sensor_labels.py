#!/usr/bin/env python3
"""Build a reversible sensor-label Magisk overlay; no driver code is changed."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile


def rodata_range(data):
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("Expected a little-endian ELF64 AArch64 sensor HAL")
    table = struct.unpack_from("<Q", data, 40)[0]
    size, count, names_index = struct.unpack_from("<HHH", data, 58)
    if size != 64 or not 0 < names_index < count or table + size * count > len(data):
        raise ValueError("Invalid section table")
    def section(index):
        return struct.unpack_from("<IIQQQQIIQQ", data, table + size * index)
    names = section(names_index)
    name_data = data[names[4]:names[4]+names[5]]
    for index in range(count):
        item = section(index)
        name = name_data[item[0]:].split(b"\0", 1)[0]
        if name == b".rodata":
            if item[2] & 5 or item[4] + item[5] > len(data):
                raise ValueError("Unexpected writable/executable .rodata or invalid bounds")
            return item[4], item[5]
    raise ValueError("Missing .rodata section")


def patch_labels(original):
    offset, size = rodata_range(original)
    source = original[offset:offset+size]
    count = source.count(b"Goldfish ")
    vendor = b"The Android Open Source Project"
    if not 12 <= count <= 32 or source.count(vendor) != 1:
        raise ValueError("Unrecognized sensor label layout; refusing to patch")
    replacement_vendor = b"Samsung Electronics".ljust(len(vendor), b" ")
    changed = source.replace(b"Goldfish ", b"Samsung  ").replace(vendor, replacement_vendor)
    patched = original[:offset] + changed + original[offset+size:]
    if len(patched) != len(original):
        raise ValueError("Patch changed ELF size")
    return patched, {"sensor_label_prefixes": count, "vendor_labels": 1,
                     "rodata_offset": offset, "rodata_size": size,
                     "original_sha256": hashlib.sha256(original).hexdigest(),
                     "patched_sha256": hashlib.sha256(patched).hexdigest(),
                     "note": "Samsung-branded lab labels; sensor hardware, values and capabilities are unchanged."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    patched, manifest = patch_labels(args.input.read_bytes())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/"patched.so").write_bytes(patched)
    (args.output_dir/"patch-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    library = "system/vendor/lib64/hw/android.hardware.sensors@2.1-impl.ranchu.so"
    with zipfile.ZipFile(args.output_dir/"s25_sensor_labels.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("module.prop", "id=s25_sensor_labels\nname=S25 Sensor Label Fixture\nversion=1.0\nversionCode=1\nauthor=EMU Lab\ndescription=Samsung-branded sensor display labels for the emulator lab; hardware unchanged.\n")
        archive.writestr("customize.sh", 'set_perm "$MODPATH/'+library+'" 0 0 0644 u:object_r:vendor_file:s0\n')
        archive.writestr(library, patched)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
