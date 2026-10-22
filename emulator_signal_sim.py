#!/usr/bin/env python3
"""Vary AVD modem test signals using the documented emulator console controls."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time


def adb_call(adb, *args):
    result = subprocess.run([adb, *args], capture_output=True, text=True, timeout=15)
    if result.returncode or "KO:" in result.stdout:
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.replace("\r", "")


def find_serial(adb, avd):
    for line in adb_call(adb, "devices").splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and columns[0].startswith("emulator-") and columns[1] == "device":
            serial = columns[0]
            if adb_call(adb, "-s", serial, "emu", "avd", "name").splitlines()[0] == avd:
                return serial
    raise RuntimeError(f"No running emulator for AVD {avd}")


def signal_profile(asu):
    return max(1, min(4, (asu - 8) // 5))


def next_rssi(rng, value, baseline):
    step = rng.choice([-1, 0, 1])
    if abs(value - baseline) > 4 and rng.randrange(3) == 0:
        step = -1 if value > baseline else 1
    return max(14, min(29, value + step))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avd", required=True)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--background", action="store_true", help="start a detached controller and write signal.log")
    parser.add_argument("--ticks", type=int, help="stop after this many updates")
    args = parser.parse_args()
    if args.background:
        if args.once or args.ticks:
            parser.error("--background cannot be combined with --once or --ticks")
        with (args.profile.parent/"signal.log").open("a") as log:
            child = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()),
                                      "--avd", args.avd, "--profile", str(args.profile.resolve())],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        time.sleep(1)
        if child.poll() is not None:
            raise RuntimeError("Controller exited; inspect signal.log")
        print(f"Started signal controller PID {child.pid}")
        return
    config = json.loads(args.profile.read_text())
    if config.get("avd") != args.avd:
        parser.error("Profile AVD does not match --avd")
    baseline = config["radio"]["initial_rssi_asu"]
    if not isinstance(baseline, int) or not 14 <= baseline <= 29:
        parser.error("Invalid RSSI in profile")
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT", os.environ.get("ANDROID_HOME", str(Path.home()/"Library/Android/sdk"))))
    adb = shutil.which("adb") or str(sdk/"platform-tools/adb")
    # Holding the file lock prevents duplicate controllers for one device profile.
    with args.profile.with_suffix(".radio.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("A signal controller already owns this device profile")
        lock.seek(0); lock.truncate(); lock.write(str(os.getpid())); lock.flush()
        serial = find_serial(adb, args.avd)
        rng = random.Random(int(config["seed"]) ^ time.time_ns())
        value, tick = baseline, 0
        while True:
            # Never mutate a reused serial belonging to a different emulator.
            actual = adb_call(adb, "-s", serial, "emu", "avd", "name").splitlines()[0]
            if actual != args.avd:
                raise RuntimeError("AVD identity changed; stopping signal controller")
            strength = signal_profile(value)
            adb_call(adb, "-s", serial, "emu", "gsm", "signal-profile", str(strength))
            adb_call(adb, "-s", serial, "emu", "gsm", "signal", str(value), "0")
            tick += 1
            state = {"avd": args.avd, "serial": serial, "pid": os.getpid(), "rssi_asu": value,
                     "signal_profile": strength, "tick": tick,
                     "updated_at": datetime.now(timezone.utc).isoformat(),
                     "note": "Console configuration; modem propagation can take 15 seconds."}
            state_path = args.profile.parent/"radio-state.json"
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2)+"\n"); temporary.replace(state_path)
            print(json.dumps(state), flush=True)
            if args.once or (args.ticks and tick >= args.ticks):
                return
            time.sleep(15)
            value = next_rssi(rng, value, baseline)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Signal simulation stopped: {error}")
