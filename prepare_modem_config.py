#!/usr/bin/env python3
"""Stage SDK modem configs beside a private AVD ramdisk before cold launch."""
import argparse
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def prepare(system_image, avd_dir):
    source = Path(system_image) / 'data/misc/modem_simulator'
    destination = Path(avd_dir) / 'data/misc/modem_simulator'
    required = source / 'iccprofile_for_sim0.xml'
    if not required.is_file():
        raise RuntimeError('System image is missing its modem SIM profile')
    files = sorted(source.rglob('*'))
    # Validate before writing, and preserve any existing per-device config.
    for path in files:
        if path.is_file():
            if path.suffix == '.xml':
                ET.parse(path)
            target = destination / path.relative_to(source)
            if target.exists() and target.read_bytes() != path.read_bytes():
                raise RuntimeError('Existing modem source config differs; refusing to overwrite it')
    for path in files:
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system-image', type=Path, required=True)
    parser.add_argument('--avd-dir', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.system_image, args.avd_dir))


if __name__ == '__main__':
    main()
