#!/usr/bin/env python3
"""Reject a frozen Android Camera preview; save evidence without capturing photos."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def meaningful_change(before, after):
    if len(before) != len(after) or not before:
        raise ValueError("preview samples must have equal nonzero sizes")
    differences = [abs(a - b) for a, b in zip(before, after)]
    return (sum(differences) / len(differences) >= 1.0
            and sum(delta >= 3 for delta in differences) / len(differences) >= 0.05)


def preview_bounds(xml):
    for node in ET.fromstring(xml).iter("node"):
        if node.get("resource-id", "").endswith(":id/progress_overlay"):
            values = tuple(map(int, re.findall(r"\d+", node.get("bounds", ""))))
            if len(values) == 4 and values[2] > values[0] and values[3] > values[1]:
                return values
    raise RuntimeError("Camera preview bounds unavailable; cannot verify the phone screen as a substitute")


def adb(serial, *args):
    return subprocess.check_output(["adb", "-s", serial, *args], timeout=20)


def require_camera_foreground(activity_dump):
    resumed = [line for line in activity_dump.splitlines()
               if "topResumedActivity=" in line or "mResumedActivity:" in line]
    if not resumed or not any("com.android.camera2/" in line for line in resumed):
        raise RuntimeError("Camera is not foreground; navigation/launcher motion is not playback")


def is_front_active(camera_dump):
    active = re.search(r'\(Camera ID: ([^,]+),', camera_dump)
    if not active:
        return False
    for block in camera_dump.split('== Camera HAL device ')[1:]:
        heading = block.splitlines()[0]
        if re.search(r'/' + re.escape(active[1]) + r' \(', heading):
            return bool(re.search(r'Facing:\s*Front', block))
    return False


def wait_and_open(avd, serial=None, timeout=180,
                  intent='android.media.action.STILL_IMAGE_CAMERA'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not serial:
            listing = subprocess.check_output(['adb', 'devices'], timeout=10).decode()
            for line in listing.splitlines()[1:]:
                parts = line.split()
                if len(parts) == 2 and parts[1] == 'device':
                    try:
                        if adb(parts[0], 'emu', 'avd', 'name').decode().splitlines()[0].strip() == avd:
                            serial = parts[0]
                            break
                    except subprocess.SubprocessError:
                        continue
        if serial:
            try:
                ready = adb(serial, 'shell', 'getprop', 'sys.boot_completed').strip() == b'1'
                if ready:
                    # Opening immediately at boot-completed can race MediaStore.
                    # Retry the app, never clear its data or recreate the device.
                    adb(serial, 'shell', 'am', 'start', '-a', intent)
                    adb(serial, 'shell', 'uiautomator', 'dump', '/sdcard/video-camera-check.xml')
                    xml = adb(serial, 'shell', 'cat', '/sdcard/video-camera-check.xml').decode()
                    preview_bounds(xml)
                    if not is_front_active(adb(serial, 'shell', 'dumpsys', 'media.camera').decode()):
                        def tap_node(text, suffix):
                            for node in ET.fromstring(text).iter('node'):
                                if node.get('resource-id', '').endswith(':id/' + suffix):
                                    x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds', '')))
                                    adb(serial, 'shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
                                    return True
                            return False
                        if not tap_node(xml, 'camera_toggle_button'):
                            if not tap_node(xml, 'mode_options_toggle'):
                                raise RuntimeError('Front-camera selector unavailable')
                            adb(serial, 'shell', 'uiautomator', 'dump', '/sdcard/video-camera-check.xml')
                            xml = adb(serial, 'shell', 'cat', '/sdcard/video-camera-check.xml').decode()
                            if not tap_node(xml, 'camera_toggle_button'):
                                raise RuntimeError('Front-camera selector unavailable')
                        time.sleep(1)
                    if is_front_active(adb(serial, 'shell', 'dumpsys', 'media.camera').decode()):
                        return serial
            except (subprocess.SubprocessError, RuntimeError, ET.ParseError):
                pass
        time.sleep(2)
    raise RuntimeError('Timed out waiting for this AVD and its front Camera preview')


def verify(serial, avd, seconds, output):
    def check_identity():
        actual = adb(serial, "emu", "avd", "name").decode().splitlines()[0].strip()
        if actual != avd:
            raise RuntimeError(f"Device identity changed: expected {avd}, got {actual}")

    check_identity()
    if not is_front_active(adb(serial, 'shell', 'dumpsys', 'media.camera').decode()):
        raise RuntimeError('The active camera is not the front camera')
    # Require the stock Camera preview rather than accepting motion in a launcher,
    # permission dialog, status bar, or another unrelated app.
    adb(serial, "shell", "uiautomator", "dump", "/sdcard/video-camera-check.xml")
    xml = adb(serial, "shell", "cat", "/sdcard/video-camera-check.xml").decode()
    x1, y1, x2, y2 = preview_bounds(xml)
    width, height = x2 - x1, y2 - y1
    # Exclude controls at the bottom of the preview and focus/edge indicators.
    region = (int(width * .8), int(height * .75),
              x1 + int(width * .1), y1 + int(height * .1))
    output.mkdir(parents=True, exist_ok=True)
    changes, previous, samples = [], None, 0
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        check_identity()
        require_camera_foreground(adb(serial, "shell", "dumpsys", "activity", "activities").decode())
        if not is_front_active(adb(serial, 'shell', 'dumpsys', 'media.camera').decode()):
            raise RuntimeError('Front camera disconnected while sampling')
        png = adb(serial, "exec-out", "screencap", "-p")
        frame = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-vf",
             "crop=%d:%d:%d:%d,scale=64:64" % region,
             "-frames:v", "1", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
            input=png, timeout=20)
        if samples == 0:
            (output / "first.png").write_bytes(png)
        if previous is not None and meaningful_change(previous, frame):
            changes.append(round(time.monotonic() - started, 3))
        previous = frame
        samples += 1
        time.sleep(.4)
    check_identity()
    require_camera_foreground(adb(serial, "shell", "dumpsys", "activity", "activities").decode())
    if not is_front_active(adb(serial, 'shell', 'dumpsys', 'media.camera').decode()):
        raise RuntimeError('The front camera was disconnected or switched during verification')
    # Re-read UI so an app crash or navigation mid-check is never a pass.
    adb(serial, "shell", "uiautomator", "dump", "/sdcard/video-camera-check.xml")
    ending_bounds = preview_bounds(adb(serial, "shell", "cat", "/sdcard/video-camera-check.xml").decode())
    if ending_bounds != (x1, y1, x2, y2):
        raise RuntimeError("Camera preview changed during playback verification")
    (output / "last.png").write_bytes(png)
    # Motion must persist in both halves, not merely during camera startup.
    moving = (len(changes) >= 3 and any(t < seconds / 2 for t in changes)
              and any(t >= seconds / 2 for t in changes))
    report = {"avd": avd, "serial": serial, "preview_bounds": [x1, y1, x2, y2],
              "preview_size": [width, height], "seconds": seconds,
              "samples": samples, "meaningful_changes": changes,
              "motion_verified": moving,
              "note": "Motion check only; verify source order and repeat boundaries separately."}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--avd", required=True)
    parser.add_argument("--wait-and-open", action="store_true")
    parser.add_argument('--camera-intent', default='android.media.action.STILL_IMAGE_CAMERA',
                        choices=['android.media.action.STILL_IMAGE_CAMERA',
                                 'android.media.action.IMAGE_CAPTURE',
                                 'android.media.action.VIDEO_CAMERA'])
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 4:
        parser.error("check at least four seconds; use two clip durations for loop testing")
    if not args.serial and not args.wait_and_open:
        parser.error('--serial is required unless --wait-and-open is used')
    args.output.mkdir(parents=True, exist_ok=True)
    report_file = args.output / 'report.json'
    report_file.write_text(json.dumps({'avd': args.avd, 'status': 'checking',
                                       'motion_verified': False}) + '\n')
    try:
        serial = (wait_and_open(args.avd, args.serial, intent=args.camera_intent)
                  if args.wait_and_open else args.serial)
        result = verify(serial, args.avd, args.seconds, args.output)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, ET.ParseError) as exc:
        report_file.write_text(json.dumps({'avd': args.avd, 'status': 'failed',
                                           'motion_verified': False, 'error': str(exc)}, indent=2) + '\n')
        parser.exit(1, f'Camera playback check FAILED: {exc}\n')
    result['status'] = 'passed' if result['motion_verified'] else 'failed'
    report_file.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result["motion_verified"]:
        parser.exit(1, "Camera playback FAILED: preview is frozen or movement is insufficient.\n")


if __name__ == "__main__":
    main()
