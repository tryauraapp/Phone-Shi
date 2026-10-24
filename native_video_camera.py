"""Idempotent native-camera preflight for the existing-phone launcher."""

from pathlib import Path
import json
from datetime import datetime, timezone
import os
import shutil
import struct
import subprocess


def running_serial(name, adb='adb'):
    try:
        listing = subprocess.check_output([adb, 'devices'], timeout=10).decode()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Could not list adb devices; refusing to guess whether this phone is running') from exc
    for line in listing.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 2 or parts[1] != 'device' or not parts[0].startswith('emulator-'):
            continue
        try:
            actual = subprocess.check_output([adb, '-s', parts[0], 'emu', 'avd', 'name'],
                                             timeout=10).decode().splitlines()[0].strip()
            if actual == name:
                return parts[0]
        except (subprocess.SubprocessError, IndexError):
            continue
    return None


def has_live_lock(directory):
    lock = directory / 'hardware-qemu.ini.lock'
    if not lock.is_file():
        return False
    try:
        value = lock.read_text().strip()
        if not value.isdigit() or int(value) < 2:
            return False
        os.kill(int(value), 0)  # Existence check only, never sends a signal.
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def viewer_preferred(name, env):
    profile = avd_directory(name, env) / 'camera/native-camera.json'
    return profile.is_file() and json.loads(profile.read_text()).get('preview_method') == 'camera2_reader'


def record_verification(name, env, report_path, method, check_exit_code=0):
    profile_path = avd_directory(name, env) / 'camera/native-camera.json'
    if not profile_path.exists():
        return
    profile = json.loads(profile_path.read_text())
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    if report.get('avd') and report.get('avd') != name:
        raise ValueError('Camera verification report belongs to a different AVD')
    passed = check_exit_code == 0 and report.get('status') == 'passed' and report.get('motion_verified') is True
    profile['status'] = ('verified_camera2_pixels' if method == 'camera2_reader' else 'verified_stock_preview') if passed else 'verification_failed'
    profile['last_verification'] = {'method': method, 'at': datetime.now(timezone.utc).isoformat(),
        'report': str(report_path), 'motion_verified': passed,
        'expected_source_sha256': profile.get('source_sha256')}
    staged = profile_path.with_name('native-camera.verification-new.json')
    staged.write_text(json.dumps(profile, indent=2) + '\n')
    staged.replace(profile_path)
    return passed


def reject_experimental_engine(directory):
    # Fingerprints of the abandoned cadence/modulo trampolines, not native
    # decoder code. Detection only: never patch or re-sign an engine here.
    prefixes = [
        (0xD10343FF, 0xF9402409, 0xF9422529, 0xB4000069, 0x9AC9082A, 0x9B098541),
        (0xD10343FF, 0xF9401801, 0x529046A9, 0x8B090021, 0xF9402409, 0xF9422529),
    ] + [(0xD10343FF, 0xF940180B, rate, 0x8B090161, 0xF9402409, 0xF9422529)
         for rate in (0x529046A9, 0x52856CE9)]
    folder = directory / 's25-emulator/qemu/darwin-aarch64'
    for name in ('qemu-system-aarch64', 'qemu-system-aarch64-headless'):
        engine = folder / name
        if engine.is_file():
            data = engine.read_bytes()
            if any(struct.pack('<6I', *prefix) in data for prefix in prefixes):
                raise ValueError(f'Abandoned experimental camera patch detected in {engine}; '
                                 'restore its verified .pre-video-loop backup before launch.')


def avd_directory(name, env):
    home = Path(env.get("ANDROID_AVD_HOME") or Path.home() / ".android/avd")
    directory = home / (name + ".avd")
    registration = home / (name + ".ini")
    if registration.exists():
        for line in registration.read_text().splitlines():
            if line.startswith("path="):
                directory = Path(line[5:])
                break
    return directory


def animation_enabled_text(text):
    """Preserve Qt INI sections/other values; do not append a duplicate key."""
    lines = text.splitlines()
    section = None
    inserted = False
    result = []
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            if section == "perAvd" and not inserted:
                result.append("virtualscene\\tv_animation=true")
                inserted = True
            section = line[1:-1]
        if section == "perAvd" and line.split("=", 1)[0].strip() == "virtualscene\\tv_animation":
            if not inserted:
                result.append("virtualscene\\tv_animation=true")
                inserted = True
        else:
            result.append(line)
    if not inserted:
        if section != "perAvd":
            result.append("[perAvd]")
        result.append("virtualscene\\tv_animation=true")
    return "\n".join(result) + "\n"


def preflight(name, env, extra):
    directory = avd_directory(name, env)
    config = directory / "config.ini"
    if not config.exists():
        return None
    values = dict(line.split("=", 1) for line in config.read_text().splitlines() if "=" in line)
    source = values.get("hw.camera.front", "").strip()
    for index, arg in enumerate(extra):
        if arg == "-camera-front" and index + 1 < len(extra):
            source = extra[index + 1]
    if source == 'environment':
        environment = directory / 'environment.ini'
        if environment.exists():
            scene_values = dict(line.split('=', 1) for line in environment.read_text().splitlines()
                                if '=' in line)
            source = scene_values.get('scene.mode', '').strip()
    if not source.startswith("videofile:"):
        return None
    path = Path(source[len("videofile:"):]).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Front-camera video is missing or empty: {path}")
    reject_experimental_engine(directory)
    settings = directory / "AVD.conf"
    before = settings.read_text() if settings.exists() else ""
    after = animation_enabled_text(before)
    if after != before:
        backup = settings.with_name("AVD.conf.before-native-camera-launch")
        if settings.exists() and not backup.exists():
            shutil.copy2(settings, backup)
        staged = settings.with_name("AVD.conf.native-camera-new")
        staged.write_text(after)
        staged.replace(settings)
    return path.resolve()
