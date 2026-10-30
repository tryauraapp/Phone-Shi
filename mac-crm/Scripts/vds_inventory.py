#!/usr/bin/env python3
"""Phone inventory for the Phone Shi CRM.

Runs on the VDS (piped over SSH as `python3 -`) and prints one JSON document
describing every phone adb can see, the systemd units and docker containers
that control them, and basic host health. Read-only: it never starts, stops
or touches a phone.
"""
import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess

PHONES_ROOT = "/opt/android-vm/phones"
SETUP_LOGS = "/opt/android-vm/setup-logs"

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
        # Port bindings come from inspect so a stopped phone keeps its serial.
        fmt = "{{.Name}}|{{.Config.Image}}|{{.State.Status}}|{{json .HostConfig.PortBindings}}"
        names = sh(["docker", "ps", "-aq"], timeout=20).split()
        lines = sh(["docker", "inspect", "-f", fmt, *names], timeout=20).splitlines() if names else []
        for line in lines:
            name, image, status, bindings = (line.split("|", 3) + ["", "", "", ""])[:4]
            name = name.lstrip("/")
            if "redroid" not in image and "android" not in image and "phone" not in image:
                continue
            serial = ""
            m = re.search(r'"5555/tcp":\s*\[\{[^}]*"HostPort":\s*"(\d+)"', bindings)
            if m:
                serial = f"emulator-{int(m.group(1)) - 1}"
            found.append({
                "kind": "docker", "name": name, "detail": f"{image} ({status})",
                "active": status == "running", "serial": serial,
            })
    return found


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def setups():
    """Phones created (or being created) by setup_vps_phone.py, keyed by serial."""
    found = {}
    for meta_path in glob.glob(os.path.join(PHONES_ROOT, "*", "phone.json")):
        meta = read_json(meta_path)
        name, port = meta.get("name"), meta.get("port")
        if not name or not port:
            continue
        found[f"emulator-{port}"] = (name, meta, os.path.dirname(meta_path))
    # A setup that has not yet written phone.json still has a log and a unit.
    for log_path in glob.glob(os.path.join(SETUP_LOGS, "*.log")):
        name = os.path.basename(log_path)[:-4]
        if not any(n == name for n, _, _ in found.values()):
            port = None
            m = re.search(r"--port (\d+)", sh(["head", "-c", "2000", log_path]))
            if m:
                port = int(m.group(1))
            found[f"emulator-{port}" if port else f"setup:{name}"] = (name, {"port": port}, "")
    out = {}
    for serial, (name, meta, directory) in found.items():
        cert = read_json(os.path.join(directory, "setup-complete.json")) if directory else {}
        unit = f"phone-setup-{name}.service"
        active = sh(["systemctl", "is-active", unit]).strip()
        log_path = os.path.join(SETUP_LOGS, name + ".log")
        log = ""
        try:
            with open(log_path, errors="replace") as fh:
                log = fh.read()[-6000:]
        except OSError:
            pass
        exit_match = re.findall(r"PHONE_SHI_EXIT=(\d+)", log)
        if active in ("active", "activating"):
            status = "running"
        elif cert.get("full_setup_complete"):
            status = "complete"
        elif cert.get("automated_base_complete"):
            status = "base-complete"
        elif exit_match and exit_match[-1] != "0":
            status = "failed"
        elif log.strip():
            status = "failed"
        else:
            status = "incomplete"
        steps = cert.get("steps") or []
        out[serial] = {
            "name": name,
            "directory": directory,
            "port": meta.get("port"),
            "grpcPort": meta.get("grpc_port"),
            "status": status,
            "automatedBaseComplete": bool(cert.get("automated_base_complete")),
            "fullSetupComplete": bool(cert.get("full_setup_complete")),
            "duckScan": cert.get("duck_scan") if isinstance(cert.get("duck_scan"), str)
                        else ((cert.get("duck_scan") or {}).get("status") or ""),
            "stepsVerified": sum(1 for st in steps if st.get("status") in ("verified", "reviewed")),
            "stepsTotal": len(steps),
            "logTail": log[-2500:],
            "unitActive": active,
        }
    return out


def next_ports(used_ports):
    port = 5554
    while port in used_ports or port + 1 in used_ports:
        port += 2
    return port, port + 3000


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
    # When two controllers claim one serial (a stopped Redroid rollback container
    # and the emulator that replaced it), the active one owns the phone.
    by_serial = {}
    for c in sorted(control, key=lambda c: (not c["active"], c["kind"] != "systemd")):
        if not c["serial"]:
            continue
        if c["serial"] in by_serial:
            c["detail"] += " (port owned by " + by_serial[c["serial"]]["name"] + ")"
            c["serial"] = ""
            continue
        by_serial[c["serial"]] = c
    setup_by_serial = setups()
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
            "setup": setup_by_serial.get(serial),
        })
    for serial, c in by_serial.items():
        if serial in seen:
            continue
        seen.add(serial)
        phones.append({
            "serial": serial, "state": "offline", "manufacturer": "", "model": "",
            "product": "", "androidVersion": "", "sdk": "", "bootCompleted": False,
            "foregroundPackage": "", "packages": [], "control": c,
            "setup": setup_by_serial.get(serial),
        })
    for serial, setup in setup_by_serial.items():
        if serial in seen or not serial.startswith("emulator-"):
            continue
        seen.add(serial)
        phones.append({
            "serial": serial, "state": "setting-up" if setup["status"] == "running" else "offline",
            "manufacturer": "", "model": "", "product": "", "androidVersion": "", "sdk": "",
            "bootCompleted": False, "foregroundPackage": "", "packages": [], "control": None,
            "setup": setup,
        })
    used = set()
    for phone in phones:
        m = re.fullmatch(r"emulator-(\d+)", phone["serial"])
        if m:
            used.add(int(m.group(1)))
    for line in sh(["ss", "-ltnH"]).splitlines():
        m = re.search(r":(\d+)\s", line)
        if m:
            used.add(int(m.group(1)))
    if shutil.which("docker"):
        # Port bindings of every container, running or not: a stopped Redroid
        # phone still owns its emulator port pair.
        names = sh(["docker", "ps", "-aq"], timeout=20).split()
        if names:
            bindings = sh(["docker", "inspect", "-f", "{{json .HostConfig.PortBindings}}", *names], timeout=20)
            for m in re.finditer(r'"HostPort":\s*"(\d+)"', bindings):
                host_port = int(m.group(1))
                used.update({host_port - 1, host_port})
    next_port, next_grpc = next_ports(used)
    print(json.dumps({
        "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": host(),
        "phones": sorted(phones, key=lambda p: p["serial"]),
        "controllers": control,
        "nextPort": next_port,
        "nextGrpcPort": next_grpc,
    }))


if __name__ == "__main__":
    main()
