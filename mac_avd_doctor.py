#!/usr/bin/env python3
"""Diagnose Mac SDK/AVD discovery; optionally register an existing AVD for Studio.

Read-only unless --register is supplied. Never launches or wipes a device.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys


def properties(path):
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith(('#', ';')):
            key, value = line.split('=', 1)
            result[key.strip()] = value.strip()
    return result


def avd_roots(env, home):
    roots = []
    for value in (env.get('ANDROID_AVD_HOME'),
                  str(Path(env['ANDROID_EMULATOR_HOME']) / 'avd') if env.get('ANDROID_EMULATOR_HOME') else None,
                  str(Path(env['ANDROID_USER_HOME']) / 'avd') if env.get('ANDROID_USER_HOME') else None,
                  str(home / '.android/avd')):
        if value:
            path = Path(value).expanduser().resolve()
            if path not in roots:
                roots.append(path)
    return roots


def register(avd_dir, name, studio_home):
    """Repair only the discovery pointer; preserve all guest data and config."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('AVD name must start with a letter/digit and contain only letters, digits, _, . or -')
    avd_dir = avd_dir.expanduser().resolve()
    config = properties(avd_dir / 'config.ini')
    if not config:
        raise ValueError('No readable config.ini in the supplied AVD directory; a Git clone does not contain an AVD')
    if config.get('AvdId', name) != name:
        raise ValueError('Name differs from config.ini AvdId; use its existing name instead of renaming the device')
    target = config.get('target', 'android-35')
    if not re.fullmatch(r'android-[A-Za-z0-9_.-]+', target):
        raise ValueError('Invalid Android target in config.ini')
    studio_home = studio_home.expanduser().resolve()
    registration = studio_home / (name + '.ini')
    existing = properties(registration)
    old_path = existing.get('path')
    if registration.exists() and not old_path:
        raise ValueError('Existing registration has no absolute path; inspect it manually before replacing')
    if old_path and Path(old_path).resolve() != avd_dir and Path(old_path).exists():
        raise ValueError('That name already points to another existing device; refusing to replace it')
    text = f'avd.ini.encoding=UTF-8\npath={avd_dir}\ntarget={target}\n'
    if registration.exists() and registration.read_text() == text:
        return registration, None
    studio_home.mkdir(parents=True, exist_ok=True)
    backup = None
    if registration.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = registration.with_name(registration.name + '.backup-' + stamp)
        shutil.copy2(registration, backup)
    # Atomic replacement on the same volume; no stale path.rel fallback.
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', dir=studio_home, prefix='.avd-registration-', delete=False) as stream:
        stream.write(text)
        staged = Path(stream.name)
    try:
        staged.replace(registration)
    finally:
        staged.unlink(missing_ok=True)
    return registration, backup


def inspect_avd(directory, sdk):
    issues = []
    config = properties(directory / 'config.ini')
    if not config:
        return ['Missing config.ini; this is not a usable AVD directory']
    image = config.get('image.sysdir.1', '')
    image_path = Path(image) if image else None
    if image_path is None or not (image_path if image_path.is_absolute() else sdk / image_path).is_dir():
        issues.append('System image is missing or image.sysdir.1 points to the old Mac; install the matching image in SDK Manager')
    for key in ('hw.camera.front', 'hw.camera.back', 'skin.path', 'disk.dataPartition.path', 'disk.ramdisk.path'):
        value = config.get(key, '')
        path = value.split(':', 1)[1] if value.startswith(('videofile:', 'imagefile:')) else value
        if path.startswith('/') and not Path(path).exists():
            issues.append(f'{key} references a missing host file; update config.ini with a local path while the device is stopped')
    manifest = directory / 's25-identifiers.json'
    if manifest.is_file():
        identity = json.loads(manifest.read_text())
        private = directory / 's25-emulator'
        if Path(identity.get('private_emulator', '')) != private or not (private / 'qemu').is_dir():
            issues.append('Private engine path is missing or belongs to the old Mac; registration alone cannot migrate this lab phone')
        if private.is_dir() and any(p.is_symlink() and not p.exists() for p in private.rglob('*')):
            issues.append('Private engine has broken SDK symlinks from the old Mac; create a fresh phone on this Mac')
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, help='SDK shown in Android Studio > Settings > Android SDK')
    parser.add_argument('--avd', help='Existing device name, not its display name')
    parser.add_argument('--avd-dir', type=Path, help='Existing .avd directory, including one copied from another Mac')
    parser.add_argument('--register', action='store_true', help='Create/repair the Studio registration, with a backup')
    parser.add_argument('--studio-avd-home', type=Path, default=Path.home() / '.android/avd',
                        help='Studio discovery directory (default: ~/.android/avd)')
    args = parser.parse_args(argv)
    if args.register and not args.avd:
        parser.error('--register requires --avd NAME')
    if args.avd and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.avd):
        parser.error('Invalid AVD name')
    sdk = (args.sdk or Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME')
                               or Path.home() / 'Library/Android/sdk')).expanduser().resolve()
    roots = avd_roots(os.environ, Path.home())
    studio_home = args.studio_avd_home.expanduser().resolve()
    if studio_home not in roots:
        roots.append(studio_home)
    print(f'Host: {platform.system()} / {platform.machine()}\nSDK: {sdk}\nStudio registration directory: {studio_home}')
    problems = []
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        problems.append('The lab creation workflow requires macOS on Apple Silicon (run a native terminal, not Rosetta)')
    for relative in ('emulator/emulator', 'platform-tools/adb'):
        if not os.access(sdk / relative, os.X_OK):
            problems.append(f'Missing executable: {sdk / relative}; install via SDK Manager')
    for relative in ('system-images/android-35/google_apis_playstore/arm64-v8a/system.img',
                     'build-tools/36.0.0/d8', 'build-tools/36.0.0/lld'):
        if not (sdk / relative).is_file():
            problems.append(f'Missing lab dependency: {sdk / relative}; install the README SDK components')
    if not os.environ.get('ANDROID_JAR') and not any(
            re.fullmatch(r'android-(?:\d+)(?:\.\d+)*', jar.parent.name)
            and int(jar.parent.name[8:].split('.')[0]) >= 35
            for jar in (sdk / 'platforms').glob('android-*/android.jar')):
        problems.append('Checker needs an Android platform jar (API 35+); install platforms;android-35 in SDK Manager')
    for tool in ('git', 'java', 'javac', 'jar', 'keytool', 'clang', 'swift'):
        if not shutil.which(tool):
            problems.append(f'Missing command: {tool}; install the README host prerequisites and check PATH')
    if os.environ.get('ANDROID_SDK_ROOT') and os.environ.get('ANDROID_HOME') and os.environ['ANDROID_SDK_ROOT'] != os.environ['ANDROID_HOME']:
        problems.append('ANDROID_SDK_ROOT and ANDROID_HOME differ; use the same SDK as Android Studio')
    for root in roots:
        print(f'AVD search directory: {root} {"(exists)" if root.is_dir() else "(absent)"}')
        for ini in sorted(root.glob('*.ini')):
            path = properties(ini).get('path')
            valid = path and (Path(path) / 'config.ini').is_file()
            print(f'  {ini.stem}: {"OK" if valid else "BROKEN registration"}')
            if not valid and not (args.register and ini == studio_home / (str(args.avd) + '.ini')):
                problems.append(f'Broken discovery pointer: {ini}; select its AVD with --avd-dir and --register to repair')
        for directory in sorted(root.glob('*.avd')):
            if not (root / (directory.stem + '.ini')).exists():
                print(f'  {directory.name}: directory exists WITHOUT registration')
                if (directory / 'config.ini').is_file() and not (args.register and args.avd == directory.stem):
                    problems.append(f'Unregistered AVD: {directory}; use --avd {directory.stem} --avd-dir PATH --register')
    directory = args.avd_dir.expanduser().resolve() if args.avd_dir else None
    if args.avd and directory is None:
        candidates = set()
        for root in roots:
            pointer = properties(root / (args.avd + '.ini')).get('path')
            for candidate in (Path(pointer) if pointer else root / (args.avd + '.avd'), root / (args.avd + '.avd')):
                if (candidate / 'config.ini').is_file():
                    candidates.add(candidate.resolve())
        if len(candidates) == 1:
            directory = candidates.pop()
        else:
            problems.append('AVD missing or ambiguous; supply --avd-dir /absolute/path/NAME.avd. A Git clone does not copy emulator data')
    if args.register:
        if directory is None:
            problems.append('Registration not changed: no existing AVD directory found')
        else:
            registration, backup = register(directory, args.avd, studio_home)
            print(f'Registered: {registration}')
            if backup:
                print(f'Previous registration backup: {backup}')
    if directory:
        print(f'Selected AVD directory: {directory}')
        problems.extend(inspect_avd(directory, sdk))
        if args.avd and not args.register:
            pointer = properties(studio_home / (args.avd + '.ini')).get('path')
            if not pointer or Path(pointer).resolve() != directory:
                command = [sys.executable, str(Path(__file__).resolve()), '--avd', args.avd,
                           '--avd-dir', str(directory), '--studio-avd-home', str(studio_home), '--register']
                problems.append('Studio registration does not match. Repair with: ' + shlex.join(command))
    emulator = sdk / 'emulator/emulator'
    if os.access(emulator, os.X_OK):
        env = dict(os.environ, ANDROID_AVD_HOME=str(studio_home), ANDROID_SDK_ROOT=str(sdk), ANDROID_HOME=str(sdk))
        result = subprocess.run([str(emulator), '-list-avds'], env=env, text=True, capture_output=True, timeout=30)
        print('Emulator discovery using Studio directory:\n' + (result.stdout.strip() or '(none)'))
        if result.returncode:
            problems.append('emulator -list-avds failed; check SDK installation and executable permissions')
        elif args.avd and args.avd not in result.stdout.splitlines():
            problems.append('The selected AVD is still absent from emulator -list-avds')
    print('Restart Android Studio, then open Tools > Device Manager > Virtual. Its SDK and AVD directory must match the paths above.')
    print('For this lab, launch with emulator_proxy.py; Studio does not apply private engine/proxy options.')
    for problem in problems:
        print('CHECK: ' + problem)
    print('Diagnostics need attention.' if problems else 'Discovery checks passed. This does not verify guest boot or app integrity.')
    return 1 if problems else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'AVD doctor: {error}', file=sys.stderr)
        sys.exit(2)
