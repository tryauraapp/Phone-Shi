#!/usr/bin/env python3
"""Shared host-platform paths and VPS capability checks."""

from __future__ import annotations

import os
from pathlib import Path
import platform


def android_sdk_root(env=None):
    env = os.environ if env is None else env
    configured = env.get("ANDROID_SDK_ROOT") or env.get("ANDROID_HOME")
    if configured:
        return Path(configured).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library/Android/sdk"
    return Path.home() / "Android/Sdk"


def host_tag():
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-aarch64"
    if system == "Linux" and machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    raise RuntimeError(f"Unsupported emulator host: {system} {machine}")


def android_abi():
    return "arm64-v8a" if host_tag() == "darwin-aarch64" else "x86_64"


def require_kvm():
    """Fail early on Linux hosts that cannot accelerate Android Emulator."""
    if platform.system() != "Linux":
        return
    kvm = Path("/dev/kvm")
    if not kvm.exists():
        raise RuntimeError("/dev/kvm is missing; nested virtualization is not enabled")
    if not os.access(kvm, os.R_OK | os.W_OK):
        raise RuntimeError("/dev/kvm is not accessible; add the service user to the kvm group")
