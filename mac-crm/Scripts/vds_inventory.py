#!/usr/bin/env python3
"""Phone inventory for the Phone Shi CRM.

Runs on the VDS (piped over SSH as `python3 -`) and prints one JSON document
describing every phone adb can see, the systemd units and docker containers
that control them, and basic host health. Read-only: it never starts, stops
or touches a phone.
"""
import datetime
import json
import os
import re
import shutil
import socket
import subprocess

ADB_CANDIDATES = [
    os.environ.get("PHONE_SHI_ADB", ""),
    "/opt/android-vm/sdk/platform-tools/adb",
    "/data/dependencies/adb/adb",
    "/usr/bin/adb",
]
ADB = next((p for p in ADB_CANDIDATES if p and os.path.exists(p)), "adb")


def sh(args, timeout=15):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def adb(serial, *args, timeout=10):
    return sh([ADB, "-s", serial, *args], timeout).strip()


def devices():
    found = []
    for line in sh([ADB, "devices", "-l"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        found.append((parts[0], parts[1]))
    return found


def props(serial):
    out = {}
    for line in adb(serial, "shell", "getprop").splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def foreground(serial):
    text = adb(serial, "shell", "dumpsys", "activity", "activities")
    m = re.search(r"(?:topResumedActivity|mResumedActivity)=ActivityRecord\{\S+ \S+ (\S+?)/", text)
    if m:
        return m.group(1)
    text = adb(serial, "shell", "dumpsys", "window")
    m = re.search(r"mCurrentFocus=Window\{\S+ \S+ (\S+?)/", text)
    return m.group(1) if m else ""


def packages(serial):
    return sorted(
        line.split(":", 1)[1].strip()
        for line in adb(serial, "shell", "pm", "list", "packages", "-3").splitlines()
        if line.startswith("package:")
    )


def controllers():
    found = []
    for line in sh(["systemctl", "list-units", "android-phone-*", "--all", "--plain", "--no-legend"]).splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        port = re.search(r"(\d{4})", unit)
        found.append({
            "kind": "systemd", "name": unit,
            "detail": " ".join(parts[4:]) or unit,
            "active": len(parts) > 2 and parts[2] == "active",
            "serial": f"emulator-{port.group(1)}" if port else "",
        })
    if shutil.which("docker"):
        fmt = "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"
        for line in sh(["docker", "ps", "-a", "--format", fmt], timeout=20).splitlines():
            name, image, status, ports = (line.split("|") + ["", "", "", ""])[:4]
            if "redroid" not in image and "android" not in image:
                continue
            serial = ""
            m = re.search(r":(\d+)->5555/tcp", ports)
            if m:
                serial = f"emulator-{int(m.group(1)) - 1}"
            found.append({
                "kind": "docker", "name": name, "detail": f"{image} ({status})",
                "active": status.lower().startswith("up"), "serial": serial,
            })
    return found


def host():
    mem = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, value = line.split(":", 1)
                mem[key] = int(value.strip().split()[0]) // 1024
    except OSError:
        pass
    disk = shutil.disk_usage("/")
    try:
        load = ", ".join(f"{v:.2f}" for v in os.getloadavg())
    except OSError:
        load = ""
    return {
        "hostname": socket.gethostname(),
        "uptime": sh(["uptime", "-p"]).strip().replace("up ", ""),
        "load": load,
        "memTotalMB": mem.get("MemTotal", 0),
        "memUsedMB": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
        "diskUsedPercent": int(disk.used * 100 / disk.total) if disk.total else 0,
        "cpuCount": os.cpu_count() or 0,
    }


def main():
    control = controllers()
    by_serial = {c["serial"]: c for c in control if c["serial"]}
    phones = []
    seen = set()
    for serial, state in devices():
        seen.add(serial)
        p = props(serial) if state == "device" else {}
        phones.append({
            "serial": serial,
            "state": state,
            "manufacturer": p.get("ro.product.manufacturer", ""),
            "model": p.get("ro.product.model", ""),
            "product": p.get("ro.product.name", ""),
            "androidVersion": p.get("ro.build.version.release", ""),
            "sdk": p.get("ro.build.version.sdk", ""),
            "bootCompleted": p.get("sys.boot_completed") == "1",
            "foregroundPackage": foreground(serial) if state == "device" else "",
            "packages": packages(serial) if state == "device" else [],
            "control": by_serial.get(serial),
        })
    for serial, c in by_serial.items():
        if serial in seen:
            continue
        phones.append({
            "serial": serial, "state": "offline", "manufacturer": "", "model": "",
            "product": "", "androidVersion": "", "sdk": "", "bootCompleted": False,
            "foregroundPackage": "", "packages": [], "control": c,
        })
    print(json.dumps({
        "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": host(),
        "phones": sorted(phones, key=lambda p: p["serial"]),
        "controllers": control,
    }))


if __name__ == "__main__":
    main()
