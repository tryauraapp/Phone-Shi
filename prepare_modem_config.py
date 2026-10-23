#!/usr/bin/env python3
"""Stage SDK modem configs beside a private AVD ramdisk before cold launch."""
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def prepare(system_image, avd_dir, lte_only=False):
    source = Path(system_image) / 'data/misc/modem_simulator'
    # First-boot userdata initialization deletes AVD/data. Keep ramdisk-adjacent
    # modem sources under a separate directory that survives that cleanup.
    destination = Path(avd_dir) / 's25-system/data/misc/modem_simulator'
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
    if lte_only:
        # Modem simulator LTE mask = 1 << 5, distinct from Android's LTE mask.
        path = destination / 'modem_nvram.json'
        if path.exists():
            instance = json.loads(path.read_text()).get('instances', {}).get('0', {})
            if instance.get('modem_technoloy') != 32 or instance.get('preferred_network_mode') != 32:
                raise RuntimeError('Existing modem config is not LTE-only; refusing to overwrite it')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {'instances': {'0': {'emergency_mode': False, 'modem_technoloy': 32,
                                        'network_selection_mode': 0, 'preferred_network_mode': 32}}}
            with path.open('x') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system-image', type=Path, required=True)
    parser.add_argument('--avd-dir', type=Path, required=True)
    parser.add_argument('--lte-only', action='store_true')
    args = parser.parse_args()
    print(prepare(args.system_image, args.avd_dir, args.lte_only))


if __name__ == '__main__':
    main()
