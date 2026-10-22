#!/usr/bin/env python3
"""Bounded setup UI reads with recovery for Android's system ANR dialog."""
import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def anr_wait_center(xml):
    """Match Android's actual ANR action, never an app's similarly named button."""
    try:
        tree = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for node in tree.iter('node'):
        if (node.get('package') != 'android' or
                node.get('resource-id') != 'android:id/aerr_wait' or
                node.get('enabled') != 'true'):
            continue
        match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if match:
            left, top, right, bottom = map(int, match.groups())
            if right > left and bottom > top:
                return (left + right) // 2, (top + bottom) // 2
    return None


def setup_ok_center(xml, package='com.topjohnwu.magisk'):
    try:
        tree = ET.fromstring(xml)
    except ET.ParseError:
        return None
    if not any(n.get('package') == package and
               n.get('text') == 'Requires additional setup' for n in tree.iter('node')):
        return None
    for node in tree.iter('node'):
        if (node.get('package') == package and node.get('text') == 'OK' and
                node.get('enabled') == 'true' and node.get('clickable') == 'true'):
            match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
            if match:
                left, top, right, bottom = map(int, match.groups())
                if right > left and bottom > top:
                    return (left + right) // 2, (top + bottom) // 2
    return None


def adb_call(serial, *args):
    result = subprocess.run(['adb', '-s', serial, *args], capture_output=True,
                            text=True, timeout=12, check=True)
    return result.stdout


def read_ui(serial, call=adb_call, pause=time.sleep):
    # Two recovery attempts per read; the caller's wall-clock deadline controls
    # longer waits. Each device command and its host process are time bounded.
    for attempt in range(3):
        xml = call(serial, 'shell',
                   'timeout 8 uiautomator dump --compressed /data/local/tmp/s25-setup-ui.xml '
                   '>/dev/null 2>&1 && cat /data/local/tmp/s25-setup-ui.xml')
        center = anr_wait_center(xml)
        if center is None:
            return xml
        if attempt == 2:
            return ''
        print('Setup: Android ANR dialog detected; selecting Wait.', file=sys.stderr)
        call(serial, 'shell', 'input', 'tap', str(center[0]), str(center[1]))
        pause(1)
    return ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    try:
        xml = read_ui(args.serial)
        if not xml:
            return 1
        print(xml.replace('>', '>\n'))
    except (subprocess.SubprocessError, OSError) as error:
        print(f'Setup UI read failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
