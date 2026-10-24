#!/usr/bin/env python3
"""Record and verify the completed Galaxy S25 setup before app signup."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


SCHEMA = 1
REQUIRED_ARTIFACTS = (
    'checker-report.json',
    'identifiers-verified.json',
    'profile/device-profile.json',
    'profile/battery.conf',
    'radio/patch-manifest.json',
    'sensors/patch-manifest.json',
    'file-aliases/manifest.json',
    'graphics/build/libGLESv2_emulation.so',
)
RUNTIME_ARTIFACTS = (
    'profile/radio-state.json',
    'location/location-state.json',
)


def _adb(serial, *args):
    return subprocess.run(['adb', '-s', serial, *args], capture_output=True, text=True,
                          timeout=20, check=True).stdout.replace('\r', '')


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_checker(path):
    report = json.loads(path.read_text())
    if report.get('redFlags') != 0 or not isinstance(report.get('findings'), list):
        raise RuntimeError('Device checker did not finish with zero red flags')
    network = [item for item in report['findings'] if item.get('name') == 'Network topology']
    if len(network) != 1 or 'Transport=CELLULAR' not in network[0].get('evidence', '') or \
            'Data network=LTE' not in network[0].get('evidence', '') or \
            '10.0.2.' in network[0].get('evidence', ''):
        raise RuntimeError('Checker report does not verify the cellular LTE network profile')
    root = [item for item in report['findings'] if item.get('name') == 'Root binaries']
    if len(root) != 1 or root[0].get('severity') != 'NOT OBSERVED':
        raise RuntimeError('Checker report does not verify app-visible root isolation')
    return {'redFlags': report['redFlags'], 'weakSignals': report.get('weakSignals')}


def _validate_live_identity(serial, avd):
    if _adb(serial, 'shell', 'getprop', 'ro.boot.qemu.avd_name').strip() != avd:
        raise RuntimeError('Connected emulator does not match the certified AVD')
    if _adb(serial, 'shell', 'getprop', 'sys.boot_completed').strip() != '1':
        raise RuntimeError('Android boot has not completed')
    abi = _adb(serial, 'shell', 'getprop', 'ro.product.cpu.abilist').strip()
    if 'arm64-v8a' not in abi.split(','):
        raise RuntimeError('Certified phone is no longer reporting ARM64')
    manufacturer = _adb(serial, 'shell', 'getprop', 'ro.product.manufacturer').strip()
    model = _adb(serial, 'shell', 'getprop', 'ro.product.model').strip()
    if manufacturer.casefold() != 'samsung' or not model.startswith('SM-S93'):
        raise RuntimeError('Connected device is not reporting the Galaxy S25 profile')
    return {'abi': abi, 'manufacturer': manufacturer, 'model': model}


def _package_installed(serial, package):
    package_paths = _adb(serial, 'shell', 'pm', 'path', package).splitlines()
    return any(line.startswith('package:') for line in package_paths)


def _validate_signup_package(serial, package):
    if not _package_installed(serial, package):
        raise RuntimeError(f'Required signup package is not installed: {package}')
    if _adb(serial, 'shell', 'su', '-c', 'id -u').strip() != '0':
        raise RuntimeError('Shell root is not available')
    denylist = _adb(serial, 'shell', 'su', '-c', 'magisk --denylist ls').splitlines()
    if not any(line.startswith(package + '|') for line in denylist):
        raise RuntimeError(f'Magisk isolation is not configured for signup package {package}')


def _validate_live(serial, avd, package):
    identity = _validate_live_identity(serial, avd)
    _validate_signup_package(serial, package)
    return identity


def record_phone_setup(serial, avd, work, packages):
    work = Path(work).resolve()
    if not packages:
        raise RuntimeError('At least one signup package is required')
    missing = [name for name in REQUIRED_ARTIFACTS + RUNTIME_ARTIFACTS
               if not (work / name).is_file()]
    if missing:
        raise RuntimeError('Full setup artifacts are missing: ' + ', '.join(missing))
    checker = _validate_checker(work / 'checker-report.json')
    live = _validate_live_identity(serial, avd)
    pending = []
    for package in packages:
        if _package_installed(serial, package):
            _validate_signup_package(serial, package)
        else:
            pending.append(package)
    artifacts = {name: _sha256(work / name) for name in REQUIRED_ARTIFACTS}
    manifest = {
        'schema': SCHEMA,
        'avd': avd,
        'authorizedSignupPackages': sorted(set(packages)),
        'completedChecks': [
            'private-stock-ramdisk', 'magisk-root', 'shell-root', 'arm64',
            'unique-identifiers', 'galaxy-s25-profile', 'cellular-lte',
            'qemu-profile', 'sensor-labels', 'file-aliases', 'graphics-labels',
            'battery-simulation', 'signal-simulation', 'bounded-gps',
            'root-isolation', 'device-checker-zero-red-flags',
        ],
        'checker': checker,
        'liveDevice': live,
        'pendingSignupPackages': pending,
        'artifacts': artifacts,
        'runtimeArtifacts': list(RUNTIME_ARTIFACTS),
    }
    destination = work / 'setup-complete.json'
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return destination


def verify_phone_setup(serial, avd, package, manifest_path=None):
    manifest_path = Path(manifest_path) if manifest_path else \
        Path.home() / 'galaxy_s25_avd_backups' / avd / 'setup' / 'setup-complete.json'
    if not manifest_path.is_file():
        raise RuntimeError('Full phone setup certificate is missing; signup is blocked')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != SCHEMA or manifest.get('avd') != avd:
        raise RuntimeError('Phone setup certificate does not match this AVD')
    if package not in manifest.get('authorizedSignupPackages', []):
        raise RuntimeError(f'Phone setup was not certified for signup package {package}')
    work = manifest_path.parent
    expected = manifest.get('artifacts', {})
    if set(expected) != set(REQUIRED_ARTIFACTS):
        raise RuntimeError('Phone setup certificate has an incomplete artifact set')
    for name, digest in expected.items():
        path = work / name
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f'Certified setup artifact is missing or changed: {name}')
    if manifest.get('runtimeArtifacts') != list(RUNTIME_ARTIFACTS):
        raise RuntimeError('Phone setup certificate has an incomplete runtime artifact set')
    for name in RUNTIME_ARTIFACTS:
        if not (work / name).is_file():
            raise RuntimeError(f'Required runtime setup artifact is missing: {name}')
    _validate_checker(work / 'checker-report.json')
    _validate_live(serial, avd, package)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--record', action='store_true')
    action.add_argument('--verify', action='store_true')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', action='append', required=True)
    args = parser.parse_args()
    if args.record:
        if not args.work:
            parser.error('--record requires --work')
        destination = record_phone_setup(args.serial, args.avd, args.work, args.package)
        print(f'Full phone setup certified: {destination}')
        return 0
    if len(args.package) != 1:
        parser.error('--verify requires exactly one --package')
    verify_phone_setup(args.serial, args.avd, args.package[0], args.manifest)
    print('Full phone setup certificate and live device checks verified.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Phone setup guard: {error}')
