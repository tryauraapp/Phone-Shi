#!/usr/bin/env python3
"""Prepare size-preserving device-path aliases for the known AVD graphics stack."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

BINARY_PATHS = (
    "vendor/lib64/egl/libEGL_emulation.so",
    "vendor/lib64/hw/android.hardware.graphics.mapper@3.0-impl-ranchu.so",
    "vendor/lib64/hw/vulkan.ranchu.so",
    "vendor/lib64/libOpenglSystemCommon.so",
    "vendor/lib64/libcodec2_goldfish_common.so",
    "vendor/bin/hw/android.hardware.graphics.allocator@3.0-service.ranchu",
    "vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu",
)
ALIASES = {
    b"/dev/goldfish_address_space": b"/dev/s25_address_space",
    b"/dev/goldfish_sync": b"/dev/s25_gpu_sync",
}
spec = importlib.util.spec_from_file_location("sensor_elf", Path(__file__).with_name("patch_sensor_labels.py"))
elf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(elf)


def patch_paths(original):
    offset, size = elf.rodata_range(original)
    source = original[offset:offset+size]
    patched = source
    counts = {}
    for old, new in ALIASES.items():
        pattern = old + b"\0"
        count = source.count(pattern)
        if original.count(pattern) != count:
            raise ValueError("Device path outside .rodata; refusing binary patch")
        if count:
            replacement = (new+b"\0").ljust(len(pattern), b"\0")
            if len(replacement) != len(pattern):
                raise ValueError("Alias does not fit existing storage")
            patched = patched.replace(pattern, replacement)
            counts[old.decode()] = count
    if not counts:
        raise ValueError("No expected device paths; wrong or already-patched binary")
    result = original[:offset]+patched+original[offset+size:]
    if len(result) != len(original):
        raise ValueError("ELF size changed")
    return result, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    results = []
    prepared = []
    for relative in BINARY_PATHS:
        original = (args.input_dir/Path(relative).name).read_bytes()
        patched, counts = patch_paths(original)
        prepared.append((relative, patched))
        results.append({"path": "/"+relative, "original_sha256": hashlib.sha256(original).hexdigest(),
                        "patched_sha256": hashlib.sha256(patched).hexdigest(), "replacements": counts})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for relative, patched in prepared:
        destination = args.output_dir/"payload"/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(patched)
    (args.output_dir/"manifest.json").write_text(json.dumps({"binaries": results}, indent=2)+"\n")
    print(f"Prepared {len(results)} binaries; changes limited to constant strings in .rodata")


if __name__ == "__main__":
    main()
