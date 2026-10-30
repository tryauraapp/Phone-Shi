#!/usr/bin/env python3
"""Persistent synthetic serial/IMEI for a Linux x86_64 Android Emulator.

Changes private host engines only. Does not root or modify the Android image.
The guest radio must obtain its IMEI from the host modem; verify that explicitly.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import struct
import subprocess
import tempfile

from device_identifiers import STOCK_IMEIS, luhn_digit, parcel_imei


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_engine(data, imei):
    if len(imei) != 15 or not imei.isascii() or not imei.isdigit() or luhn_digit(imei[:14]) != imei[-1]:
        raise ValueError('Expected a Luhn-valid 15-digit synthetic IMEI')
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 62:
        raise ValueError('Expected a little-endian Linux ELF64 x86_64 engine')
    for stock in STOCK_IMEIS:
        if data.count(stock + b'\0') != 1:
            raise ValueError('Unsupported engine: modem constant count differs')
    for stock in STOCK_IMEIS:
        data = data.replace(stock + b'\0', imei.encode() + b'\0')
    # LLVM also inlines MiscService::HandleGetIMEI's short std::string into
    # two overlapping eight-byte movabs immediates (SDK 37.2.13 x86_64).
    # Replacing only the string table leaves AT+CGSN=2 returning the default.
    compiled = (b'\x48\xb8' + b'86740002' + b'\x48\x89\x44\x24\x39\x48\xb8' +
                b'22047199' + b'\x48\x89\x44\x24\x40')
    if data.count(compiled) != 1:
        raise ValueError('Unsupported engine: compiled modem IMEI pattern differs')
    replacement = (b'\x48\xb8' + imei[:8].encode() + b'\x48\x89\x44\x24\x39\x48\xb8' +
                   imei[7:].encode() + b'\x48\x89\x44\x24\x40')
    data = data.replace(compiled, replacement)
    # Emulator 37.2.13 puts '-' between '_' and ',' in its serial regex.
    # libc++ rejects that reversed range before validating any supplied serial.
    # Move '-' to the end of the class, preserving the intended character set.
    broken_regex = b'^[a-zA-Z0-9._-,]+$\0'
    if data.count(broken_regex) > 1:
        raise ValueError('Ambiguous serial validation expression')
    data = data.replace(broken_regex, b'^[a-zA-Z0-9._,-]+$\0')
    return data


def reserve(registry, avd):
    registry = Path(registry)
    registry.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(registry, timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS linux_avd_identity '
                   '(avd TEXT PRIMARY KEY, serial TEXT UNIQUE NOT NULL, imei TEXT UNIQUE NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT serial, imei FROM linux_avd_identity WHERE avd=?', (avd,)).fetchone()
        if existing:
            result = dict(serial=existing[0], imei=existing[1])
        else:
            for _ in range(100):
                body = '0044' + ''.join(str(secrets.randbelow(10)) for _ in range(10))
                result = dict(serial='LAB' + secrets.token_hex(8).upper(), imei=body + luhn_digit(body))
                try:
                    db.execute('INSERT INTO linux_avd_identity VALUES (?,?,?)',
                               (avd, result['serial'], result['imei']))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError('Could not reserve unique identifiers')
    registry.chmod(0o600)
    return result


def prepare(sdk, avd_dir, avd, registry, baseline_android_id=None):
    sdk, avd_dir = Path(sdk).resolve(), Path(avd_dir).resolve()
    if not (avd_dir / 'config.ini').is_file():
        raise ValueError('AVD configuration is missing')
    source = sdk / 'emulator'
    names = ('qemu-system-x86_64', 'qemu-system-x86_64-headless')
    originals = {name: (source / 'qemu/linux-x86_64' / name).read_bytes() for name in names}
    # Reject an unsupported SDK before reserving identifiers or writing engines.
    for data in originals.values():
        patch_engine(data, '004400000000008')
    manifest = avd_dir / 'linux-identifiers.json'
    private = avd_dir / 'private-emulator'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved['avd'] != avd or saved['source_sha256'] != {n: digest(b) for n, b in originals.items()}:
            raise ValueError('Existing identity belongs to another AVD or SDK version')
        for name in names:
            if digest((private / 'qemu/linux-x86_64' / name).read_bytes()) != saved['patched_sha256'][name]:
                raise ValueError('Existing private engine differs from its manifest')
        if (private / 'emulator').is_symlink() or digest((private / 'emulator').read_bytes()) != digest((source / 'emulator').read_bytes()):
            raise ValueError('Private launcher must be an unchanged physical copy of the SDK launcher')
        return saved
    if private.exists():
        raise ValueError('Unregistered private engine directory exists; refusing overwrite')
    identity = reserve(registry, avd)
    temporary = Path(tempfile.mkdtemp(prefix='.identity-', dir=avd_dir))
    try:
        for item in source.iterdir():
            if item.name == 'emulator':
                shutil.copy2(item, temporary / item.name)
            elif item.name != 'qemu':
                (temporary / item.name).symlink_to(item)
        engines = temporary / 'qemu/linux-x86_64'
        engines.mkdir(parents=True)
        (engines / 'lib64').symlink_to(source / 'lib64')
        hashes = {}
        for name, data in originals.items():
            patched = patch_engine(data, identity['imei'])
            target = engines / name
            target.write_bytes(patched)
            target.chmod(0o755)
            hashes[name] = digest(patched)
        temporary.rename(private)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    identity.update(schema=1, kind='synthetic-linux-emulator-identifiers', avd=avd,
                    private_emulator=str(private), source_sdk=str(sdk),
                    source_sha256={n: digest(b) for n, b in originals.items()}, patched_sha256=hashes)
    if baseline_android_id is not None:
        identity['baseline_android_id_sha256'] = digest(baseline_android_id.encode())
    with manifest.open('x') as out:
        json.dump(identity, out, indent=2)
        out.write('\n')
    manifest.chmod(0o600)
    return identity


def verify(adb, serial, manifest):
    expected = json.loads(Path(manifest).read_text())
    def shell(*args):
        return subprocess.check_output([adb, '-s', serial, 'shell', *args], text=True, timeout=30).strip()
    actual_serial = shell('getprop', 'ro.serialno')
    boot_serial = shell('getprop', 'ro.boot.serialno')
    actual_imei = parcel_imei(shell('service', 'call', 'iphonesubinfo', '1', 's16', 'com.android.shell'))
    if actual_serial != expected['serial'] or boot_serial != expected['serial']:
        raise RuntimeError('Android serial read-back differs from reserved serial')
    if actual_imei != expected['imei']:
        raise RuntimeError('Android telephony IMEI differs from reserved host-modem IMEI')
    android_id_hash = digest(shell('settings', '--user', '0', 'get', 'secure', 'android_id').encode())
    if expected.get('baseline_android_id_sha256', android_id_hash) != android_id_hash:
        raise RuntimeError('Existing secure Android ID changed unexpectedly')
    if shell('getenforce') != 'Enforcing' or shell('getprop', 'ro.debuggable') != '0':
        raise RuntimeError('Guest security configuration changed unexpectedly')
    return dict(avd=expected['avd'], serial_match=True, boot_serial_match=True, imei_match=True,
                secure_android_id_sha256=android_id_hash, selinux='Enforcing', debuggable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    for name in ('sdk', 'avd-dir', 'avd', 'registry'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--baseline-serial')
    p.add_argument('--adb', default='adb')
    v = commands.add_parser('verify')
    v.add_argument('--adb', default='adb')
    v.add_argument('--serial', required=True)
    v.add_argument('--manifest', required=True)
    v.add_argument('--output', required=True)
    launch = commands.add_parser('launch', help='Validate persistent identity and launch this AVD')
    for name in ('sdk', 'avd-dir', 'avd', 'registry'):
        launch.add_argument('--' + name, required=True)
    launch.add_argument('emulator_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'prepare':
        baseline = None
        if args.baseline_serial:
            baseline = subprocess.check_output([args.adb, '-s', args.baseline_serial, 'shell', 'settings',
                                                '--user', '0', 'get', 'secure', 'android_id'], text=True).strip()
            if len(baseline) != 16 or any(c not in '0123456789abcdef' for c in baseline):
                raise RuntimeError('Could not read existing secure Android ID')
        prepare(args.sdk, args.avd_dir, args.avd, args.registry, baseline)
        print('Private host engines and persistent serial/IMEI manifest prepared.')
    elif args.command == 'launch':
        saved = prepare(args.sdk, args.avd_dir, args.avd, args.registry)
        extra = args.emulator_args
        if extra[:1] == ['--']:
            extra = extra[1:]
        platform_args = []
        if (Path(args.avd_dir) / 'android17-s25-platform.json').exists():
            from s25_android17_platform import launch_options
            if '-sysdir' in extra or '-system' in extra:
                raise ValueError('Saved S25 platform cannot be combined with another image override')
            platform_args = launch_options(args.avd_dir)
        executable = str(Path(saved['private_emulator']) / 'emulator')
        os.execv(executable, [executable, '-avd', args.avd, '-qemu-top-dir', saved['private_emulator'],
                              '-android-serialno', saved['serial'], *platform_args, *extra])
    else:
        result = verify(args.adb, args.serial, args.manifest)
        out = Path(args.output)
        out.write_text(json.dumps(result, indent=2) + '\n')
        out.chmod(0o600)
        print('Android serial, boot serial, telephony IMEI and security state verified.')


if __name__ == '__main__':
    main()
