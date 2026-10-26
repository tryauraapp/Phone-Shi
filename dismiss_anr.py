#!/usr/bin/env python3
"""Auto-dismiss 'System UI isn't responding' (ANR) dialogs by tapping Wait.

    python3 dismiss_anr.py emulator-5554
    python3 dismiss_anr.py emulator-5554 --interval 2
"""

import re
import subprocess
import sys
import time

def get_ui_xml(serial):
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "uiautomator", "dump", "/dev/stdout"],
            capture_output=True, text=True, timeout=10)
        return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""

def find_wait_button(xml):
    match = re.search(
        r'text="Wait"[^/]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if match:
        x1, y1, x2, y2 = map(int, match.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None

def tap(serial, x, y):
    subprocess.run(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)],
                   timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else "emulator-5554"
    interval = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--interval" else 3
    print(f"Watching {serial} for ANR dialogs every {interval}s ...", flush=True)
    dismissed = 0
    while True:
        xml = get_ui_xml(serial)
        if "isn’t responding" in xml or "isn't responding" in xml:
            coords = find_wait_button(xml)
            if coords:
                tap(serial, *coords)
                dismissed += 1
                t = time.strftime("%H:%M:%S")
                print(f"{t} dismissed ANR #{dismissed} at {coords}", flush=True)
        time.sleep(interval)

if __name__ == "__main__":
    main()
