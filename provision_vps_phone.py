#!/usr/bin/env python3
"""Create and certify one Linux x86-64 Android phone for the VPS fleet.

The worker is intentionally separate from the web process.  It records every
stage on disk so a control-panel restart does not lose job state.  Google Play
authentication and installation remain a visible manual checkpoint; --resume
certifies the phone only after the requested package is actually installed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parent
_host_spec = importlib.util.spec_from_file_location(
    "_phone_shi_host_platform", REPO / "host_platform.py")
_host_module = importlib.util.module_from_spec(_host_spec)
_host_spec.loader.exec_module(_host_module)
android_sdk_root = _host_module.android_sdk_root
require_kvm = _host_module.require_kvm
APP_PACKAGES = {
    "bumble": "com.bumble.app",
    "tinder": "com.tinder",
    "pof": "com.pof.android",
}
IMAGE = "system-images;android-35;google_apis_playstore;x86_64"


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(4))
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class Job:
    def __init__(self, data, avd):
        self.data = Path(data)
        self.avd = avd
        self.folder = self.data / "provisioning" / avd
        self.status_path = self.folder / "status.json"
        self.request_path = self.folder / "request.json"
        self.folder.mkdir(parents=True, exist_ok=True)

    def update(self, phase, stage, progress, message, **extra):
        value = {
            "avd": self.avd,
            "phase": phase,
            "stage": stage,
            "progress": progress,
            "message": message,
            "updatedAt": stamp(),
            **extra,
        }
        atomic_json(self.status_path, value)
        print(f"[{progress:3d}%] {stage}: {message}", flush=True)


def run(command, *, input_text=None, timeout=300, capture=True):
    print("+ " + " ".join(str(value) for value in command), flush=True)
    return subprocess.run(
        [str(value) for value in command], input=input_text, text=True,
        capture_output=capture, timeout=timeout, check=True)


def valid_name(value):
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", value or ""):
        raise ValueError("Phone name must use 3–64 letters, numbers, dots, underscores or dashes")
    return value


def paths(avd):
    sdk = android_sdk_root()
    avd_home = Path(os.environ.get("ANDROID_AVD_HOME", Path.home() / ".android/avd"))
    backups = Path(os.environ.get("PHONE_BACKUPS", Path.home() / "galaxy_s25_avd_backups"))
    return sdk, avd_home, avd_home / f"{avd}.avd", backups / avd / "setup"


def set_config(path, values):
    existing = {}
    order = []
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                existing[key] = value
                order.append(key)
    existing.update({key: str(value) for key, value in values.items()})
    for key in values:
        if key not in order:
            order.append(key)
    path.write_text("\n".join(f"{key}={existing[key]}" for key in order) + "\n")


def find_serial(adb, avd):
    result = run([adb, "devices"], timeout=10).stdout
    for line in result.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 2 or columns[1] != "device":
            continue
        serial = columns[0]
        observed = run(
            [adb, "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"],
            timeout=10).stdout.strip()
        if observed == avd:
            return serial
    return None


def wait_for_boot(adb, avd, timeout=420):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            serial = find_serial(adb, avd)
            if serial:
                completed = run(
                    [adb, "-s", serial, "shell", "getprop", "sys.boot_completed"],
                    timeout=10).stdout.strip()
                if completed == "1":
                    return serial
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(3)
    raise RuntimeError("Android did not complete its first boot")


def adb_value(adb, serial, *args):
    return run([adb, "-s", serial, *args], timeout=30).stdout.replace("\r", "").strip()


def package_installed(adb, serial, package):
    result = subprocess.run(
        [str(adb), "-s", serial, "shell", "pm", "path", package],
        capture_output=True, text=True, timeout=30)
    return result.returncode == 0 and "package:" in result.stdout


def apply_runtime(adb, serial, location, setup):
    timezone = location["timezone"]
    subprocess.run([str(adb), "-s", serial, "shell", "settings", "put",
                    "global", "auto_time_zone", "0"], timeout=30, check=True)
    subprocess.run([str(adb), "-s", serial, "shell", "cmd", "alarm",
                    "set-timezone", timezone], timeout=30, check=True)
    subprocess.run([str(adb), "-s", serial, "shell", "cmd", "location",
                    "set-location-enabled", "true"], timeout=30, check=True)
    subprocess.run([str(adb), "-s", serial, "emu", "geo", "fix",
                    str(location["longitude"]), str(location["latitude"])],
                   timeout=30, check=True)
    level = secrets.randbelow(36) + 55
    subprocess.run([str(adb), "-s", serial, "emu", "power", "ac", "off"],
                   capture_output=True, timeout=30)
    subprocess.run([str(adb), "-s", serial, "emu", "power", "capacity", str(level)],
                   timeout=30, check=True)
    profile = setup / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "battery.conf").write_text(f"LEVEL={level}\n")
    atomic_json(profile / "radio-state.json", {
        "avd": setup.parent.name, "serial": serial, "network": "LTE",
        "carrier": "T-Mobile", "updatedAt": stamp(),
    })
    location_folder = setup / "location"
    location_folder.mkdir(parents=True, exist_ok=True)
    atomic_json(location_folder / "location-state.json", {
        "avd": setup.parent.name, "serial": serial,
        "center_latitude": location["latitude"],
        "center_longitude": location["longitude"], "updatedAt": stamp(),
    })


def actual_device(adb, serial):
    return {
        "manufacturer": adb_value(adb, serial, "shell", "getprop", "ro.product.manufacturer"),
        "model": adb_value(adb, serial, "shell", "getprop", "ro.product.model"),
        "android": adb_value(adb, serial, "shell", "getprop", "ro.build.version.release"),
        "abi": adb_value(adb, serial, "shell", "getprop", "ro.product.cpu.abi"),
    }


def create(args, job):
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("VPS phone creation requires Linux x86-64")
    require_kvm()
    sdk, avd_home, avd_dir, setup = paths(args.avd)
    adb = sdk / "platform-tools/adb"
    emulator = sdk / "emulator/emulator"
    avdmanager = sdk / "cmdline-tools/latest/bin/avdmanager"
    image = sdk / "system-images/android-35/google_apis_playstore/x86_64"
    for required in (adb, emulator, avdmanager, image / "system.img"):
        if not required.exists():
            raise RuntimeError(f"Required Android component is missing: {required}")
    if (avd_home / f"{args.avd}.ini").exists() or avd_dir.exists() or setup.parent.exists():
        raise RuntimeError("A phone or saved setup already uses this name")
    if shutil.disk_usage(avd_home).free < 12 * 1024 ** 3:
        raise RuntimeError("At least 12 GB free disk space is required for a new phone")
    if not args.proxy_key or not Path(args.proxy_key).is_file():
        raise RuntimeError("Save a NodeMaven API key before creating a phone")
    if not args.camera_video or not Path(args.camera_video).is_file():
        raise RuntimeError("A per-phone camera video is required")

    request = {
        "avd": args.avd, "app": args.app, "region": args.region, "city": args.city,
        "ram": args.ram, "cores": args.cores, "cameraVideo": str(Path(args.camera_video)),
        "createdAt": stamp(),
    }
    atomic_json(job.request_path, request)
    setup.mkdir(parents=True, exist_ok=False)

    job.update("provisioning", "preflight", 5, "KVM, Android SDK, storage and inputs verified")
    job.update("provisioning", "create-avd", 14, "Creating a fresh Android 15 Google Play x86-64 AVD")
    avd_home.mkdir(parents=True, exist_ok=True)
    run([avdmanager, "create", "avd", "--name", args.avd, "--package", IMAGE,
         "--device", "pixel_6", "--force"], input_text="no\n", timeout=180)
    if not avd_dir.is_dir():
        raise RuntimeError("avdmanager did not create the expected AVD directory")
    set_config(avd_dir / "config.ini", {
        "hw.ramSize": args.ram,
        "hw.cpu.ncore": args.cores,
        "disk.dataPartition.size": "12G",
        "hw.keyboard": "yes",
        "hw.gpu.enabled": "yes",
        "hw.gpu.mode": "auto",
        "skin.name": "1080x2340",
        "skin.path": "_no_skin",
        "hw.lcd.width": "1080",
        "hw.lcd.height": "2340",
        "hw.lcd.density": "420",
        "showDeviceFrame": "no",
    })

    job.update("provisioning", "proxy", 28, f"Provisioning a city-targeted T-Mobile proxy for {args.city}, {args.region}")
    proxy_path = setup / "nodemaven-proxy"
    run([sys.executable, "-I", REPO / "nodemaven_proxy.py", "--avd", args.avd,
         "--key-file", args.proxy_key, "--output", proxy_path,
         "--region", args.region, "--city", args.city], timeout=180, capture=False)
    location_result = run(
        [sys.executable, "-I", REPO / "emulator_proxy.py", "--location",
         "--proxy-file", proxy_path], timeout=90)
    location = json.loads(location_result.stdout)
    atomic_json(setup / "proxy-location.json", location)

    job.update("provisioning", "camera", 42, "Preparing the per-phone 3:4 native camera feed")
    run([sys.executable, "-I", REPO / "configure_video_camera.py",
         "--avd", args.avd, "--video", args.camera_video,
         "--preview-size", "1080x1440"], timeout=900, capture=False)

    job.update("provisioning", "first-boot", 58, "Starting the phone through its private proxy")
    log_path = Path(os.environ.get("ACCOUNT_PANEL_DATA", REPO / "control-panel/data")) / "fleet" / f"{args.avd}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "w", encoding="utf-8")
    os.chmod(log_path, 0o600)
    launcher = subprocess.Popen(
        [sys.executable, "-I", str(REPO / "emulator_proxy.py"), "--avd", args.avd,
         "--check-video-camera", "--camera-viewer"],
        cwd=REPO, env=dict(os.environ, PYTHONUNBUFFERED="1"),
        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    stream.close()
    atomic_json(job.folder / "launcher.json", {"pid": launcher.pid, "startedAt": stamp()})
    serial = wait_for_boot(adb, args.avd)

    job.update("provisioning", "runtime", 72, "Applying proxy timezone, GPS and bounded battery state")
    apply_runtime(adb, serial, location, setup)
    device = actual_device(adb, serial)
    if device["abi"] != "x86_64":
        raise RuntimeError(f"Unexpected Android ABI: {device['abi']}")
    atomic_json(setup / "profile/device-profile.json", device)

    package = APP_PACKAGES[args.app]
    job.update("manual-required", "google-play", 82,
               f"Complete Google Play sign-in and install {args.app.title()} on the visible phone",
               serial=serial, package=package)
    subprocess.run(
        [str(adb), "-s", serial, "shell", "am", "start", "-a",
         "android.intent.action.VIEW", "-d", f"market://details?id={package}"],
        capture_output=True, text=True, timeout=30)


def resume(args, job):
    request = json.loads(job.request_path.read_text())
    sdk, _, _, setup = paths(args.avd)
    adb = sdk / "platform-tools/adb"
    serial = wait_for_boot(adb, args.avd, timeout=60)
    package = APP_PACKAGES[request["app"]]
    job.update("checking", "verify-app", 86, f"Checking that {request['app'].title()} is installed")
    if not package_installed(adb, serial, package):
        raise RuntimeError(
            f"{request['app'].title()} is not installed yet; finish Google Play installation and retry")
    location = json.loads((setup / "proxy-location.json").read_text())
    apply_runtime(adb, serial, location, setup)
    device = actual_device(adb, serial)
    camera = json.loads((paths(args.avd)[2] / "camera/native-camera.json").read_text())
    if camera.get("status") != "verified_camera2_pixels":
        raise RuntimeError("The Camera2 texture-motion check has not passed")
    certificate = {
        "schema": 2,
        "platform": "linux-x86_64",
        "avd": args.avd,
        "authorizedSignupPackages": [package],
        "completedChecks": [
            "kvm", "android-15-x86_64", "city-targeted-mobile-proxy",
            "proxy-timezone", "proxy-gps", "bounded-battery",
            "native-camera2-texture-motion", "requested-app-installed",
        ],
        "liveDevice": device,
        "location": location,
        "app": request["app"],
        "certifiedAt": stamp(),
        "limitations": [
            "Standard Google Android Emulator identity; not certified as a physical Samsung device",
            "Google Play authentication is user-completed",
        ],
    }
    atomic_json(setup / "setup-complete.json", certificate)
    job.update("ready", "complete", 100, "VPS phone setup verified and saved",
               serial=serial, package=package, certified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avd", required=True, type=valid_name)
    parser.add_argument("--data", default=os.environ.get(
        "ACCOUNT_PANEL_DATA", str(REPO / "control-panel/data")))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--app", choices=sorted(APP_PACKAGES))
    parser.add_argument("--region")
    parser.add_argument("--city")
    parser.add_argument("--ram", type=int, default=2048)
    parser.add_argument("--cores", type=int, default=4)
    parser.add_argument("--camera-video")
    parser.add_argument("--proxy-key")
    args = parser.parse_args()
    if not args.resume:
        if not all((args.app, args.region, args.city, args.camera_video)):
            parser.error("creation requires --app, --region, --city and --camera-video")
        if not 1536 <= args.ram <= 4096:
            parser.error("--ram must be between 1536 and 4096 MB")
        if not 2 <= args.cores <= 8:
            parser.error("--cores must be between 2 and 8")
    job = Job(args.data, args.avd)
    try:
        if args.resume:
            resume(args, job)
        else:
            create(args, job)
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        job.update("failed", "failed", 0, str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
