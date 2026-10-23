#!/usr/bin/env python3
"""Reserve persistent synthetic identifiers and prepare a private emulator engine."""
import argparse
from contextlib import closing
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import struct
import subprocess

STOCK_IMEIS = (b'867400022047199', b'358240051111110')


def random_mac(prefix):
    tail = secrets.token_hex(5)
    return prefix + ':' + ':'.join(tail[i:i+2] for i in range(0, 10, 2))


def luhn_digit(body):
    total = 0
    for index, digit in enumerate(body):
        value = int(digit) * (2 if index % 2 else 1)
        total += value // 10 + value % 10
    return str((-total) % 10)


def reserve(registry, name):
    registry.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(registry, timeout=30)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS devices '
                   '(avd TEXT, serial TEXT UNIQUE, imei TEXT UNIQUE, android_id TEXT UNIQUE)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(devices)')}
        for column in ('wifi_mac', 'cellular_mac', 'network_cidr'):
            if column not in columns:
                db.execute(f'ALTER TABLE devices ADD COLUMN {column} TEXT')
            db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS devices_{column} ON devices({column})')
        db.execute('BEGIN IMMEDIATE')
        for _ in range(100):
            body = '0044' + ''.join(str(secrets.randbelow(10)) for _ in range(10))
            identity = dict(avd=name, serial='S25' + secrets.token_hex(8).upper(),
                            imei=body + luhn_digit(body), android_id=secrets.token_hex(8),
                            wifi_mac=random_mac('02'), cellular_mac=random_mac('06'),
                            network_cidr=f'10.{secrets.randbelow(254) + 1}.{2 * secrets.randbelow(128)}.0/23')
            try:
                db.execute('INSERT INTO devices (avd, serial, imei, android_id, wifi_mac, cellular_mac, network_cidr) '
                           'VALUES (?, ?, ?, ?, ?, ?, ?)',
                           tuple(identity[key] for key in ('avd', 'serial', 'imei', 'android_id',
                                                           'wifi_mac', 'cellular_mac', 'network_cidr')))
            except sqlite3.IntegrityError:
                continue
            registry.chmod(0o600)
            return identity
    raise RuntimeError('Could not reserve unique identifiers')


def network_profile(cidr):
    subnets = list(ipaddress.ip_network(cidr).subnets(new_prefix=24))
    profile = {}
    for kind, subnet in zip(('radio', 'wifi'), subnets):
        profile[kind + '_subnet'] = str(subnet)
        profile[kind + '_ip'] = str(subnet[100])
        profile[kind + '_options'] = (f'ipv6=off,net={subnet},host={subnet[2]},'
                                       f'dhcpstart={subnet[100]}')
    return profile


def patch_engine(data, imei):
    replacement = imei.encode()
    if not re.fullmatch(rb'\d{15}', replacement) or luhn_digit(imei[:14]) != imei[-1]:
        raise ValueError('Invalid synthetic IMEI')
    for stock in STOCK_IMEIS:
        if data.count(stock + b'\0') != 1:
            raise RuntimeError('Unsupported emulator engine: expected IMEI constants were not found exactly once')
        data = data.replace(stock + b'\0', replacement + b'\0')
    return data


NETWORK_SYMBOLS = {
    'address': '__ZN10cuttlefish5modem12DeviceConfig22ril_address_and_prefixEv',
    'gateway': '__ZN10cuttlefish5modem12DeviceConfig11ril_gatewayEv',
    'dns': '__ZN10cuttlefish5modem12DeviceConfig7ril_dnsEv',
}


def short_string_stub(value, capacity):
    """ARM64 libc++ alternate-layout SSO return through the caller's x8 pointer."""
    encoded = value.encode('ascii')
    if not 1 <= len(encoded) <= (18 if capacity == 44 else 15):
        raise ValueError('Network string exceeds the supported inline return size')
    words = [0, 0x3D800100]  # ldr q0, literal; str q0, [x8]
    if capacity == 44:
        tail = int.from_bytes(encoded[16:].ljust(2, b'\0'), 'little')
        words += [0x52800009 | (tail << 5), 0xB9001109]  # mov w9; str w9, [x8,#16]
    words += [0x52800009 | (len(encoded) << 5), 0x39005D09, 0xD65F03C0]
    literal_offset = len(words) * 4
    words[0] = 0x9C000000 | ((literal_offset // 4) << 5)
    code = struct.pack('<' + 'I' * len(words), *words) + encoded[:16].ljust(16, b'\0')
    if len(code) != capacity:
        raise ValueError('Unexpected network stub size')
    return code


def patch_network_engine(data, network):
    """Keep modem AT replies in sync with libslirp; patch only this private engine."""
    if struct.unpack_from('<II', data) != (0xFEEDFACF, 0x100000C):
        raise RuntimeError('Network patch requires a thin ARM64 Mach-O engine')
    ncmds = struct.unpack_from('<I', data, 16)[0]
    offset, segments, symbols = 32, [], {}
    symtab = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, offset)
        if cmd == 0x19:
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', data, offset + 24)
            segments.append((vmaddr, fileoff, filesize))
        elif cmd == 2:
            symtab = struct.unpack_from('<IIII', data, offset + 8)
        offset += size
    if symtab is None:
        raise RuntimeError('Engine has no symbol table; network patch refused')
    symoff, nsyms, stroff, strsize = symtab
    for index in range(nsyms):
        name_offset, kind, section, desc, address = struct.unpack_from('<IBBHQ', data, symoff + index * 16)
        if not name_offset or name_offset >= strsize:
            continue
        start = stroff + name_offset
        name = data[start:data.index(b'\0', start)].decode('ascii', errors='replace')
        if name in NETWORK_SYMBOLS.values():
            symbols[name] = address
    subnet = ipaddress.ip_network(network['radio_subnet'])
    values = {'address': network['radio_ip'] + '/' + str(subnet.prefixlen),
              'gateway': str(subnet[2]), 'dns': str(subnet[3])}
    output = bytearray(data)
    for key, symbol in NETWORK_SYMBOLS.items():
        if symbol not in symbols:
            raise RuntimeError(f'Missing modem {key} symbol; network patch refused')
        address = symbols[symbol]
        positions = [fileoff + address - vmaddr for vmaddr, fileoff, size in segments
                     if vmaddr <= address < vmaddr + size]
        if len(positions) != 1:
            raise RuntimeError('Invalid network function location')
        position = positions[0]
        capacity, stock_length = (44, 12) if key == 'address' else (36, 8)
        original = data[position:position + capacity]
        if (struct.unpack_from('<I', original)[0] != 0x52800009 | (stock_length << 5)
                or struct.unpack_from('<I', original, 4)[0] != 0x39005D09
                or struct.unpack_from('<I', original, capacity - 4)[0] != 0xD65F03C0):
            raise RuntimeError('Unsupported modem function layout; network patch refused')
        output[position:position + capacity] = short_string_stub(values[key], capacity)
    return bytes(output)


def prepare(sdk, avd_dir, name, registry):
    manifest = avd_dir / 's25-identifiers.json'
    if manifest.exists():
        raise RuntimeError('Identifiers already exist; refusing to regenerate them')
    source = sdk / 'emulator'
    engines = [source / 'qemu/darwin-aarch64' / filename for filename in
               ('qemu-system-aarch64', 'qemu-system-aarch64-headless')]
    # Check compatibility before reserving or copying anything.
    for engine in engines:
        patch_engine(engine.read_bytes(), '004400000000008')
    identity = reserve(registry, name)
    identity['network'] = network_profile(identity['network_cidr'])
    identity['hardware'] = dict(model='SM-S931B', manufacturer='samsung', android_release='15',
                                api_level=35, soc='SM8750', soc_manufacturer='QTI')
    identity['system_settings'] = {
        'screen_brightness_mode': '0',
        'screen_brightness': str(80 + secrets.randbelow(101)),
        'screen_off_timeout': secrets.choice(('30000', '60000', '120000')),
        'haptic_feedback_enabled': str(secrets.randbelow(2)),
        'font_scale': secrets.choice(('1.0', '1.05', '1.1')),
    }
    # An exported test UA is not an override for a third-party app's HTTP stack.
    identity['user_agent'] = (f'Dalvik/2.1.0 (Linux; U; Android 15; SM-S931B '
                              f'Build/AP3A.240905.015.A2) S25Profile/{identity["android_id"]}')
    identity['user_agent_status'] = 'exported-only; Bumble override not applied'
    private = avd_dir / 's25-emulator'
    private.mkdir()
    # Resources remain shared and read-only; only the per-AVD engines are copied.
    for path in source.iterdir():
        if path.name == 'emulator':
            shutil.copy2(path, private / path.name)
        elif path.name != 'qemu':
            (private / path.name).symlink_to(path)
    engine_dir = private / 'qemu/darwin-aarch64'
    engine_dir.mkdir(parents=True)
    (engine_dir / 'lib64').symlink_to(source / 'lib64')
    # The relocated engine also searches @loader_path for Qt dependencies.
    for library in (source / 'lib64/qt/lib').glob('*.dylib'):
        (engine_dir / library.name).symlink_to(library)
    hashes = {}
    for source_engine in engines:
        data = source_engine.read_bytes()
        target = engine_dir / source_engine.name
        target.write_bytes(patch_network_engine(patch_engine(data, identity['imei']), identity['network']))
        target.chmod(0o755)
        subprocess.run(['codesign', '--force', '--sign', '-', '--preserve-metadata=entitlements', str(target)],
                       check=True, capture_output=True, text=True)
        subprocess.run(['codesign', '--verify', str(target)], check=True, capture_output=True, text=True)
        hashes[source_engine.name] = hashlib.sha256(data).hexdigest()
    identity.update(private_emulator=str(private.resolve()), source_sha256=hashes,
                    kind='synthetic-emulator-identifiers', network_patch='modem-sso-v1')
    with manifest.open('x') as stream:
        json.dump(identity, stream, indent=2)
        stream.write('\n')
    manifest.chmod(0o600)
    with (avd_dir / 's25-network.conf').open('x') as stream:
        stream.write(f'WIFI_MAC={identity["wifi_mac"]}\n')
        stream.write(f'RADIO_IP={identity["network"]["radio_ip"]}\n')
    (avd_dir / 's25-network.conf').chmod(0o600)
    return identity


def repair_network(sdk, avd_dir):
    """Upgrade existing private engines without changing any reserved identifier."""
    manifest = avd_dir / 's25-identifiers.json'
    identity = json.loads(manifest.read_text())
    network = network_profile(identity['network_cidr'])
    private = Path(identity['private_emulator']) / 'qemu/darwin-aarch64'
    prepared = []
    for name, expected_hash in identity['source_sha256'].items():
        source = sdk / 'emulator/qemu/darwin-aarch64' / name
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise RuntimeError('SDK engine changed since creation; automatic network repair refused')
        target = private / (name + '.network-new')
        target.write_bytes(patch_network_engine(patch_engine(data, identity['imei']), network))
        target.chmod(0o755)
        subprocess.run(['codesign', '--force', '--sign', '-', '--preserve-metadata=entitlements', str(target)],
                       check=True, capture_output=True, text=True)
        subprocess.run(['codesign', '--verify', str(target)], check=True, capture_output=True, text=True)
        prepared.append((target, private / name))
    for staged, target in prepared:
        staged.replace(target)
    identity.update(network=network, network_patch='modem-sso-v1')
    temporary = manifest.with_suffix('.json.network-new')
    temporary.write_text(json.dumps(identity, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(manifest)


def parcel_imei(parcel):
    words = []
    for line in parcel.splitlines():
        match = re.match(r'\s*0x[0-9a-fA-F]+:\s*((?:[0-9a-fA-F]{8}\s*)+)', line)
        if match:
            words.extend(re.findall(r'[0-9a-fA-F]{8}', match[1]))
    decoded = b''.join(int(word, 16).to_bytes(4, 'little') for word in words).decode('utf-16-le', errors='ignore')
    match = re.search(r'(?<!\d)\d{15}(?!\d)', decoded)
    if not match:
        raise RuntimeError('Could not read modem IMEI through the Android telephony service')
    return match[0]


def verify(adb, serial, identity):
    def call(*args):
        result = subprocess.run([adb, '-s', serial, *args], check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip().replace('\r', '')
    def root(script):
        # Send compound scripts through stdin: adb joins shell arguments and
        # can otherwise leave part of `su -c if ...; then ...; fi` outside su.
        result = subprocess.run([adb, '-s', serial, 'shell', 'su'], input=script + '\n',
                                check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip().replace('\r', '')
    if call('emu', 'avd', 'name').splitlines()[0] != identity['avd']:
        raise RuntimeError('AVD identity mismatch')
    actual = dict(serial=call('shell', 'getprop', 'ro.serialno'),
                  android_id=call('shell', 'settings', '--user', '0', 'get', 'secure', 'android_id'),
                  imei=parcel_imei(root('service call iphonesubinfo 1 s16 com.android.shell')))
    if 'network' in identity:
        addresses = call('shell', 'ip', '-4', '-o', 'addr', 'show')
        network = ipaddress.ip_network(identity['network']['radio_subnet'])
        interfaces = []
        for line in addresses.splitlines():
            match = re.search(r'^\d+:\s+([a-zA-Z0-9_.-]+)(?:@\S+)?\s+inet\s+([0-9.]+)/\d+', line)
            if match and ipaddress.ip_address(match[2]) in network:
                interfaces.append(match[1])
        if len(interfaces) != 1:
            raise RuntimeError('Expected cellular private subnet is not active')
        actual['cellular_mac'] = root(f'cat /sys/class/net/{interfaces[0]}/address').lower()
        # Wi-Fi stays disabled. If its interface exists, verify its reserved MAC too.
        wifi = root('if [ -e /sys/class/net/wlan0/address ]; then\ncat /sys/class/net/wlan0/address\nelse\nexit 0\nfi')
        if wifi:
            actual['wifi_mac'] = wifi.lower()
    if 'system_settings' in identity:
        actual['system_settings'] = {key: call('shell', 'settings', '--user', '0', 'get', 'system', key)
                                     for key in identity['system_settings']}
    drift = {}
    for key, value in actual.items():
        if key == 'system_settings':
            # Preferences are mutable and the emulator itself resets display
            # timeout on a cold start. Record drift without calling it an ID failure.
            drift = {setting: {'expected': identity[key][setting], 'actual': observed}
                     for setting, observed in value.items() if observed != identity[key][setting]}
            continue
        if value != identity[key]:
            raise RuntimeError(f'{key} read-back mismatch: expected {identity[key]!r}, got {value!r}')
    if drift:
        actual['settings_drift'] = drift
    return actual


def initialize(adb, serial, identity):
    def call(*args):
        return subprocess.run([adb, '-s', serial, *args], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if call('emu', 'avd', 'name').splitlines()[0] != identity['avd']:
        raise RuntimeError('AVD identity mismatch')
    call('shell', 'settings', '--user', '0', 'put', 'secure', 'android_id', identity['android_id'])
    for key, value in identity['system_settings'].items():
        call('shell', 'settings', '--user', '0', 'put', 'system', key, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd-dir', required=True, type=Path)
    parser.add_argument('--name')
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--verify-serial')
    parser.add_argument('--initialize-serial')
    parser.add_argument('--repair-network', action='store_true')
    parser.add_argument('--adb', default='adb')
    args = parser.parse_args()
    if args.repair_network:
        if args.sdk is None:
            parser.error('--sdk is required for network repair')
        repair_network(args.sdk, args.avd_dir)
        print('Private modem network functions repaired; existing identifiers preserved.')
    elif args.verify_serial or args.initialize_serial:
        identity = json.loads((args.avd_dir / 's25-identifiers.json').read_text())
        if args.initialize_serial:
            initialize(args.adb, args.initialize_serial, identity)
        else:
            print(json.dumps(verify(args.adb, args.verify_serial, identity)))
    else:
        if not all((args.name, args.sdk, args.registry)):
            parser.error('--name, --sdk and --registry are required for preparation')
        prepare(args.sdk, args.avd_dir, args.name, args.registry)
        print('Unique IMEI, serial and Android ID reserved; private emulator engines prepared.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
