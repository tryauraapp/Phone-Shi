#!/usr/bin/env python3
"""Validate a Linux VPS before installing or starting Phone Shi V2."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from host_platform import android_abi, android_sdk_root, host_tag, require_kvm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-missing-sdk", action="store_true")
    args = parser.parse_args()
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    try:
        tag = host_tag()
        check("host", tag == "linux-x86_64", tag)
    except RuntimeError as exc:
        check("host", False, exc)
    try:
        require_kvm()
        check("kvm", True, "/dev/kvm is available")
    except RuntimeError as exc:
        check("kvm", False, exc)

    sdk = android_sdk_root()
    check("sdk", (sdk / "platform-tools/adb").is_file() or args.allow_missing_sdk, sdk)
    check("emulator", (sdk / "emulator/emulator").is_file() or args.allow_missing_sdk,
          sdk / "emulator/emulator")
    check("abi", android_abi() == "x86_64", android_abi())
    for binary in ("python3", "ffmpeg", "java", "unzip"):
        check(binary, bool(shutil.which(binary)), shutil.which(binary) or "missing")

    cpu = ""
    try:
        cpu = Path("/proc/cpuinfo").read_text()
    except OSError:
        pass
    check("nested-virtualization", " vmx " in f" {cpu.replace(chr(10), ' ')} " or
          " svm " in f" {cpu.replace(chr(10), ' ')} ", "VMX or SVM CPU flag")

    if args.json:
        print(json.dumps({"ok": all(item["ok"] for item in checks), "checks": checks}, indent=2))
    else:
        for item in checks:
            print(("PASS" if item["ok"] else "FAIL") + f"  {item['name']}: {item['detail']}")
    return 0 if all(item["ok"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
