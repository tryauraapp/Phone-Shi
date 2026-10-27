#!/usr/bin/env python3
"""Restore and verify the supported runtime state of a certified VPS phone."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
_worker_spec = importlib.util.spec_from_file_location(
    "_phone_shi_vps_worker", ROOT / "provision_vps_phone.py")
_worker = importlib.util.module_from_spec(_worker_spec)
_worker_spec.loader.exec_module(_worker)
actual_device = _worker.actual_device
apply_runtime = _worker.apply_runtime
package_installed = _worker.package_installed
paths = _worker.paths
wait_for_boot = _worker.wait_for_boot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avd", required=True)
    args = parser.parse_args()
    sdk, _, _, setup = paths(args.avd)
    certificate = json.loads((setup / "setup-complete.json").read_text())
    if (certificate.get("schema") != 2 or certificate.get("platform") != "linux-x86_64"
            or certificate.get("avd") != args.avd):
        raise RuntimeError("VPS setup certificate does not match this phone")
    adb = sdk / "platform-tools/adb"
    serial = wait_for_boot(adb, args.avd)
    location = json.loads((setup / "proxy-location.json").read_text())
    apply_runtime(adb, serial, location, setup)
    observed = actual_device(adb, serial)
    expected = certificate.get("liveDevice") or {}
    if observed.get("abi") != "x86_64" or any(
            observed.get(key) != expected.get(key) for key in ("manufacturer", "model", "abi")):
        raise RuntimeError("VPS phone identity changed from its saved setup")
    package = (certificate.get("authorizedSignupPackages") or [None])[0]
    if not package or not package_installed(adb, serial, package):
        raise RuntimeError("The certified app is missing")
    print(json.dumps({
        "avd": args.avd, "serial": serial, "timezone": location["timezone"],
        "latitude": location["latitude"], "longitude": location["longitude"],
        "status": "vps-runtime-restored",
    }), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        raise SystemExit(f"VPS phone runtime restoration failed: {exc}")
