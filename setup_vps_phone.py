#!/usr/bin/env python3
"""Create, restore and verify a phone using the saved rootless VPS standard."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

from linux_avd_identity import prepare, verify

HERE = Path(__file__).resolve().parent
DEFAULT_PROFILE = HERE / 'phone_setup_standard.json'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
        json.dump(value, out, indent=2)
        out.write('\n')
    temporary.replace(path)


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def call(*args, timeout=60):
    return subprocess.run(list(map(str, args)), text=True, timeout=timeout,
                          capture_output=True, check=True).stdout.strip()


def shell(meta, *args):
    return call(meta['sdk'] + '/platform-tools/adb', '-s', 'emulator-' + str(meta['port']),
                'shell', shlex.join(list(map(str, args))))


def validate_request(name, port, grpc_port):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', name):
        raise ValueError('Use an AVD name of 1–64 letters, digits, dots, underscores or hyphens')
    if not 5554 <= port <= 5682 or port % 2:
        raise ValueError('Choose an even emulator port between 5554 and 5682')
    if not 1024 <= grpc_port <= 65535 or grpc_port in (port, port + 1):
        raise ValueError('Choose a separate unprivileged gRPC port')


def config(name, profile):
    r = profile['resources']
    values = {
        'AvdId': name, 'avd.ini.displayname': name, 'avd.ini.encoding': 'UTF-8',
        'PlayStore.enabled': 'true', 'abi.type': 'x86_64',
        'disk.dataPartition.size': str(r['data_gb']) + 'G', 'fastboot.forceColdBoot': 'yes',
        'hw.accelerometer': 'yes', 'hw.cpu.arch': 'x86_64', 'hw.cpu.ncore': r['cores'],
        'hw.dPad': 'no', 'hw.gps': 'yes', 'hw.gpu.enabled': 'yes', 'hw.gpu.mode': 'software',
        'hw.keyboard': 'yes', 'hw.lcd.density': r['density'], 'hw.lcd.height': r['height'],
        'hw.lcd.width': r['width'], 'hw.mainKeys': 'no', 'hw.ramSize': r['ram_mb'],
        'hw.sdCard': 'no', 'hw.sensors.orientation': 'yes', 'hw.sensors.proximity': 'yes',
        'image.sysdir.1': profile['image'] + '/', 'runtime.network.latency': 'none',
        'runtime.network.speed': 'full', 'showDeviceFrame': 'no', 'skin.dynamic': 'yes',
        'tag.display': 'Google Play', 'tag.id': 'google_apis_playstore',
        'target': 'android-37.0', 'vm.heapSize': 512,
    }
    return ''.join(f'{key}={value}\n' for key, value in values.items())


def environment(meta):
    root = Path(meta['root'])
    home = root / 'home'
    return dict(ANDROID_HOME=meta['sdk'], ANDROID_SDK_ROOT=meta['sdk'],
                ANDROID_AVD_HOME=str(root / 'avd'), ANDROID_EMULATOR_HOME=str(home / '.android'),
                ANDROID_USER_HOME=str(home / '.android'), ANDROID_SDK_HOME=str(home),
                XDG_RUNTIME_DIR=str(root / 'run'), HOME=str(home), ANDROID_EMULATOR_USE_SYSTEM_LIBS='1')


def launcher(meta, profile):
    args = [sys.executable, str(HERE / 'linux_avd_identity.py'), 'launch',
            '--sdk', meta['sdk'], '--avd-dir', meta['avd_dir'], '--avd', meta['name'],
            '--registry', meta['registry'], '--', '-port', str(meta['port']),
            '-grpc', str(meta['grpc_port']), '-grpc-use-token', '-no-window', '-no-audio',
            '-no-snapshot', '-accel', 'on', '-gpu', 'software', '-feature', '-GLAsyncSwap',
            '-timezone', profile['timezone']]
    return ('#!/bin/sh\nset -eu\n' + ''.join('export ' + k + '=' + shlex.quote(v) + '\n'
            for k, v in environment(meta).items()) + 'exec ' + shlex.join(args) + '\n')


def wait_boot(meta, timeout=240):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            if shell(meta, 'getprop', 'sys.boot_completed') == '1':
                return
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise RuntimeError('Phone did not finish booting; its data and logs have been retained')


def console(meta, commands):
    token = (Path(meta['root']) / 'home/.emulator_console_auth_token').read_text().strip()
    with socket.create_connection(('127.0.0.1', meta['port']), timeout=10) as connection:
        stream = connection.makefile('rwb', buffering=0)
        def response():
            while True:
                line = stream.readline()
                if not line:
                    raise RuntimeError('Emulator console closed')
                line = line.decode().strip()
                if line == 'OK':
                    return
                if line.startswith('KO:'):
                    raise RuntimeError(line)
        response()
        for command in ['auth ' + token, *commands]:
            stream.write((command + '\n').encode())
            response()
        stream.write(b'quit\n')


def apply_runtime(meta, profile):
    wait_boot(meta)
    r, battery = profile['resources'], profile['battery']
    # Display reconfiguration can restore WindowManager's cached rotation mode.
    # Apply it before user preferences, then lock through WindowManager itself.
    shell(meta, 'wm', 'size', f"{r['width']}x{r['height']}")
    shell(meta, 'wm', 'density', str(r['density']))
    for namespace, key in [('system', 'system_settings'), ('global', 'global_settings'),
                           ('secure', 'secure_settings')]:
        for name, value in profile[key].items():
            shell(meta, 'settings', 'put', namespace, name, value)
    shell(meta, 'cmd', 'window', 'user-rotation', 'lock', '0')
    shell(meta, 'cmd', 'alarm', 'set-timezone', profile['timezone'])
    shell(meta, 'svc', 'wifi', 'disable')
    shell(meta, 'svc', 'data', 'enable')
    console(meta, ['gsm voice home', 'gsm data home', 'power present true', 'power ac off',
                   'power health ' + battery['health'], 'power status ' + battery['status'],
                   'power capacity ' + str(battery['level'])])
    # The emulator's asynchronous post-boot display setup can reset rotation
    # after sys.boot_completed. Require a stable window, restoring the requested
    # native lock if that late setup changes it.
    stable = 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (shell(meta, 'settings', 'get', 'system', 'accelerometer_rotation') == '0' and
                shell(meta, 'settings', 'get', 'system', 'user_rotation') == '0'):
            stable += 1
            if stable >= 6:
                return
        else:
            stable = 0
            shell(meta, 'cmd', 'window', 'user-rotation', 'lock', '0')
        time.sleep(1)
    raise RuntimeError('Portrait lock did not stabilize after emulator boot setup')


def capture_android_id(meta):
    value = shell(meta, 'settings', '--user', '0', 'get', 'secure', 'android_id')
    if not re.fullmatch('[0-9a-f]{16}', value):
        raise RuntimeError('Android ID is not ready')
    digest = hashlib.sha256(value.encode()).hexdigest()
    with sqlite3.connect(meta['registry']) as db:
        db.execute('CREATE TABLE IF NOT EXISTS linux_android_ids (avd TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL)')
        old = db.execute('SELECT digest FROM linux_android_ids WHERE avd=?', (meta['name'],)).fetchone()
        if old and old[0] != digest:
            raise RuntimeError('Android ID differs from the saved device registry')
        if not old:
            db.execute('INSERT INTO linux_android_ids VALUES (?,?)', (meta['name'], digest))
    manifest = Path(meta['avd_dir']) / 'linux-identifiers.json'
    identity = read(manifest)
    if identity.get('baseline_android_id_sha256', digest) != digest:
        raise RuntimeError('Android ID differs from the saved identity manifest')
    identity['baseline_android_id_sha256'] = digest
    save(manifest, identity)


def verify_runtime(meta, profile):
    wait_boot(meta)
    evidence = verify(meta['sdk'] + '/platform-tools/adb', 'emulator-' + str(meta['port']),
                      Path(meta['avd_dir']) / 'linux-identifiers.json')
    for prop, expected in [('ro.build.version.sdk', '37'), ('ro.secure', '1'), ('ro.adb.secure', '1')]:
        if shell(meta, 'getprop', prop) != expected:
            raise RuntimeError('Unexpected Android security/platform property: ' + prop)
    if shell(meta, 'sh', '-c', 'command -v su || true'):
        raise RuntimeError('Guest su is present')
    if profile.get('platform_profile'):
        for key, value in profile['platform_profile']['identity'].items():
            if shell(meta, 'getprop', 'ro.product.' + key) != value:
                raise RuntimeError('S25 platform identity differs: ' + key)
        from s25_android17_platform import launch_options
        if not launch_options(meta['avd_dir']):
            raise RuntimeError('Saved S25 platform manifest is missing')
    for namespace, key in [('system', 'system_settings'), ('global', 'global_settings'), ('secure', 'secure_settings')]:
        for name, expected in profile[key].items():
            if shell(meta, 'settings', 'get', namespace, name) != expected:
                raise RuntimeError('Saved setting differs: ' + name)
    r = profile['resources']
    if f"{r['width']}x{r['height']}" not in shell(meta, 'wm', 'size') or str(r['density']) not in shell(meta, 'wm', 'density'):
        raise RuntimeError('Display profile differs')
    if shell(meta, 'getprop', 'persist.sys.timezone') != profile['timezone']:
        raise RuntimeError('Time zone differs')
    until = time.monotonic() + 60
    while True:
        battery = shell(meta, 'dumpsys', 'battery')
        network = shell(meta, 'dumpsys', 'connectivity')
        default = re.search(r'Active default network: (\d+)', network)
        active = next((line for line in network.splitlines()
                       if default and 'NetworkAgentInfo{network{' + default[1] + '}' in line), '')
        native_battery = all(re.search(r'^\s*' + re.escape(k) + ': ' + v + r'\s*$', battery, re.M)
                             for k, v in {'level': str(profile['battery']['level']), 'status': '3',
                                          'health': '2', 'present': 'true', 'AC powered': 'false',
                                          'USB powered': 'false', 'Wireless powered': 'false'}.items())
        if native_battery and 'Transports: CELLULAR' in active and '&VALIDATED' in active:
            break
        if time.monotonic() >= until:
            raise RuntimeError('Native battery or validated cellular default network is not ready')
        time.sleep(2)
    package = shell(meta, 'dumpsys', 'package', profile['duck']['package'])
    if not re.search(r'\bversionCode=' + str(profile['duck']['version_code']) + r'\b', package):
        raise RuntimeError('Expected unchanged Duck Detector package is missing')
    apk_paths = shell(meta, 'pm', 'path', profile['duck']['package']).splitlines()
    if len(apk_paths) != 1 or not apk_paths[0].startswith('package:'):
        raise RuntimeError('Unexpected Duck APK layout')
    apk = subprocess.check_output([meta['sdk'] + '/platform-tools/adb', '-s',
                                  'emulator-' + str(meta['port']), 'exec-out',
                                  shlex.join(['cat', apk_paths[0][8:]])], timeout=60)
    if hashlib.sha256(apk).hexdigest() != profile['duck']['sha256']:
        raise RuntimeError('Installed Duck APK hash differs from the saved unchanged APK')
    evidence.update(profile=profile['id'], verified_at=datetime.now(timezone.utc).isoformat(),
                    manufacturer=shell(meta, 'getprop', 'ro.product.manufacturer'),
                    model=shell(meta, 'getprop', 'ro.product.model'),
                    android_release=shell(meta, 'getprop', 'ro.build.version.release'), sdk=37,
                    battery_level=profile['battery']['level'], battery_status='discharging',
                    cellular_default_validated=True, wifi=False, guest_su=False,
                    duck_version_code=profile['duck']['version_code'], duck_apk_sha256=profile['duck']['sha256'])
    return evidence


def install_units(meta):
    directory = Path(meta['directory'])
    phone = meta['service']
    runtime = f"android-profile-{meta['port']}.service"
    units = {
        phone: '[Unit]\nDescription=Standard rootless Android phone\nAfter=network.target\n'
               '[Service]\nType=simple\nExecStart=' + str(directory / 'launch.sh') +
               '\nExecStop=' + shlex.join([sys.executable, str(HERE / 'setup_vps_phone.py'), 'flush',
                                           '--metadata', str(directory / 'phone.json')]) +
               '\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=30\nKillMode=mixed\n'
               '[Install]\nWantedBy=multi-user.target\n',
        runtime: '[Unit]\nDescription=Saved phone settings, native battery and radio\nAfter=' + phone +
                 '\nPartOf=' + phone + '\n[Service]\nType=oneshot\nExecStart=' +
                 shlex.join([sys.executable, str(HERE / 'setup_vps_phone.py'), 'runtime',
                             '--metadata', str(directory / 'phone.json')]) +
                 '\nTimeoutStartSec=360\n[Install]\nWantedBy=' + phone + '\n'
    }
    for name, contents in units.items():
        with (Path('/etc/systemd/system') / name).open('x') as out:
            out.write(contents)
    call('systemctl', 'daemon-reload')
    call('systemctl', 'enable', phone, runtime)


def preflight(args, profile):
    validate_request(args.name, args.port, args.grpc_port)
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or os.geteuid() != 0:
        raise ValueError('Run on the Linux x86_64 VPS as root; macOS uses its separate legacy workflow')
    if not os.access('/dev/kvm', os.R_OK | os.W_OK):
        raise ValueError('KVM is unavailable')
    root, sdk = Path(args.root).resolve(), Path(args.sdk).resolve()
    if any(c in str(root) + str(sdk) + str(HERE) for c in (' ', '\n', '%', '"', '\\')):
        raise ValueError('Use simple absolute paths without spaces or systemd escape characters')
    for name, expected in profile['sdk_engine_sha256'].items():
        if sha(sdk / 'emulator/qemu/linux-x86_64' / name) != expected:
            raise ValueError('SDK engine is not the saved supported version: ' + name)
    for name, expected in profile['image_sha256'].items():
        if sha(sdk / profile['image'] / name) != expected:
            raise ValueError('System image differs from the saved standard: ' + name)
    if sha(args.duck_apk) != profile['duck']['sha256']:
        raise ValueError('Duck APK differs from the saved unchanged APK')
    if profile.get('platform_profile') and sha(root / profile['platform_profile']['asset']) != profile['platform_profile']['sha256']:
        raise ValueError('Tested Android 17 S25 platform asset differs')
    if shutil.disk_usage(root).free < 8 * 1024**3:
        raise ValueError('At least 8 GiB free storage is required')
    for port in (args.port, args.port + 1, args.grpc_port):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    if not (root / 'home/.android/adbkey.pub').is_file():
        raise ValueError('Existing authorized controller ADB key is missing from the emulator home')
    for path in [root / 'avd' / (args.name + '.avd'), root / 'avd' / (args.name + '.ini'),
                 root / 'phones' / args.name, Path('/etc/systemd/system') / f'android-phone-{args.port}.service',
                 Path('/etc/systemd/system') / f'android-profile-{args.port}.service']:
        if path.exists():
            raise ValueError('Refusing to overwrite an existing phone or service: ' + str(path))
    return root, sdk


def create(args, profile):
    root, sdk = preflight(args, profile)
    directory = root / 'phones' / args.name
    avd = root / 'avd' / (args.name + '.avd')
    directory.mkdir(parents=True, mode=0o700)
    avd.mkdir(mode=0o700)
    for path in (root / 'home/.android', root / 'run'):
        path.mkdir(parents=True, exist_ok=True)
    meta = dict(schema=1, name=args.name, root=str(root), sdk=str(sdk), avd_dir=str(avd),
                directory=str(directory), registry=str(root / 'identities.sqlite3'),
                port=args.port, grpc_port=args.grpc_port, service=f'android-phone-{args.port}.service',
                profile=str(directory / 'setup-profile.json'))
    save(directory / 'phone.json', meta)
    save(meta['profile'], profile)
    (avd / 'config.ini').write_text(config(args.name, profile))
    with (root / 'avd' / (args.name + '.ini')).open('x') as out:
        out.write('avd.ini.encoding=UTF-8\npath=' + str(avd) + '\ntarget=android-37.0\n')
    if profile.get('platform_profile'):
        from s25_android17_platform import install
        install(avd, sdk, root / profile['platform_profile']['asset'])
    prepare(sdk, avd, args.name, meta['registry'])
    launch = directory / 'launch.sh'
    launch.write_text(launcher(meta, profile))
    launch.chmod(0o700)
    install_units(meta)
    finish(meta, profile, args.duck_apk)


def finish(meta, profile, duck_apk):
    directory, sdk = Path(meta['directory']), Path(meta['sdk'])
    if sha(duck_apk) != profile['duck']['sha256']:
        raise ValueError('Duck APK differs from the saved unchanged APK')
    try:
        call('systemctl', 'start', meta['service'], timeout=360)
        wait_boot(meta)
        capture_android_id(meta)
        call(sdk / 'platform-tools/adb', '-s', 'emulator-' + str(meta['port']), 'install',
             '-r', str(Path(duck_apk).resolve()), timeout=120)
        call('systemctl', 'start', f"android-profile-{meta['port']}.service", timeout=360)
        save(directory / 'verification-boot1.json', verify_runtime(meta, profile))
        shell(meta, 'sync')
        call('systemctl', 'restart', meta['service'], timeout=360)
        # The dependent profile is a oneshot; it must complete before certifying.
        call('systemctl', 'start', f"android-profile-{meta['port']}.service", timeout=360)
        save(directory / 'verification-boot2.json', verify_runtime(meta, profile))
        shell(meta, 'sync')
        save(directory / 'setup-complete.json', dict(profile=profile['id'], avd=meta['name'],
             automated_base_complete=True, full_setup_complete=False, duck_scan='interactive-checkpoint-pending',
             conditional_steps={str(i): 'not-requested' for i in (29, 30, 31)},
             steps=[dict(step, status=('verified' if step['mode'] == 'automatic' else
                                      'not-requested' if step['mode'] == 'conditional' else 'pending'))
                    for step in profile['steps']]))
        call('systemctl', 'enable', meta['service'], f"android-profile-{meta['port']}.service")
    except Exception:
        # Preserve all files for recovery, but never auto-boot an incomplete new phone.
        subprocess.run(['systemctl', 'disable', '--now', meta['service']])
        raise
    print('Standard base setup verified across two boots. Duck startup/scan remains interactive.')
    print('Saved phone record: ' + str(directory / 'setup-complete.json'))


def scan_counts(report, profile):
    if not re.search(r'App Version\s*:[^\n]*\(Build ' + str(profile['duck']['version_code']) + r'\)', report):
        raise ValueError('Report is from a different Duck build')
    counts = {}
    for name in ('Danger', 'Warning', 'Ready', 'Pending'):
        matches = re.findall(r'^\s*\[[^\]]+\]\s*' + name + r'\s*:\s*(\d+)\s*$', report, re.M)
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous report statistic: ' + name)
        counts[name.lower()] = int(matches[0])
    if counts != profile['duck']['comparison_baseline']:
        raise ValueError('Duck scan differs from the saved baseline; review it before completing setup')
    return counts


def record_scan(meta, profile, report_path):
    directory = Path(meta['directory'])
    certificate = read(directory / 'setup-complete.json')
    if not certificate.get('automated_base_complete'):
        raise ValueError('Complete the automated base setup first')
    report = Path(report_path).read_text()
    counts = scan_counts(report, profile)
    save(directory / 'verification-current.json', verify_runtime(meta, profile))
    destination = directory / 'duck-scan-report.txt'
    destination.write_text(report)
    destination.chmod(0o600)
    certificate.update(full_setup_complete=True, duck_scan=dict(status='reviewed', counts=counts,
        report=str(destination), report_sha256=sha(destination), recorded_at=datetime.now(timezone.utc).isoformat()))
    for step in certificate.get('steps', []):
        if step['id'] == 34:
            step['status'] = 'reviewed'
    save(directory / 'setup-complete.json', certificate)
    print('Duck report matches the saved baseline; complete setup review recorded.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('plan')
    p = commands.add_parser('create')
    p.add_argument('--name', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--grpc-port', type=int, required=True)
    p.add_argument('--root', default='/opt/android-vm')
    p.add_argument('--sdk', default='/opt/android-vm/sdk')
    p.add_argument('--duck-apk', required=True)
    p = commands.add_parser('record-scan', help='Record this phone\'s reviewed exported Duck report')
    p.add_argument('--metadata', required=True)
    p.add_argument('--report', required=True)
    for name in ('runtime', 'verify', 'flush'):
        p = commands.add_parser(name)
        p.add_argument('--metadata', required=True)
    p = commands.add_parser('resume', help='Resume a retained incomplete setup without wiping it')
    p.add_argument('--metadata', required=True)
    p.add_argument('--duck-apk', required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        profile = read(DEFAULT_PROFILE)
        print(profile['display_name'] + ' (' + profile['id'] + ')')
        for step in profile['steps']:
            print(f"{step['id']:2}. [{step['mode']}] {step['name']}")
    elif args.command == 'create':
        # Serialize provisioning on this host so port/name reservations cannot race.
        with open('/run/lock/phone-shi-setup.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            create(args, read(DEFAULT_PROFILE))
    else:
        meta = read(args.metadata)
        profile = read(meta['profile'])
        if args.command == 'record-scan':
            record_scan(meta, profile, args.report)
        elif args.command == 'resume':
            certificate = Path(meta['directory']) / 'setup-complete.json'
            if certificate.exists() and read(certificate).get('automated_base_complete'):
                raise ValueError('Base setup is already complete; use verify instead of restarting it')
            finish(meta, profile, args.duck_apk)
        elif args.command == 'flush':
            shell(meta, 'sync')
        elif args.command == 'runtime':
            apply_runtime(meta, profile)
            print('Saved settings and native battery/radio profile applied.')
        else:
            save(Path(meta['directory']) / 'verification-current.json', verify_runtime(meta, profile))
            print('Saved phone profile verified.')


if __name__ == '__main__':
    main()
