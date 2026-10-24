#!/usr/bin/env python3
"""Bounded Magisk manager setup, permission requests and failure diagnostics."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_ui import adb_call

PACKAGE = 'com.topjohnwu.magisk'


def center(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
    if not match:
        return None
    left, top, right, bottom = map(int, match.groups())
    return ((left + right) // 2, (top + bottom) // 2) if right > left and bottom > top else None


def shell_toggle(xml):
    """Only match a switch in the smallest ancestor containing a Shell label."""
    tree = ET.fromstring(xml)
    for row in reversed(list(tree.iter('node'))):
        nodes = list(row.iter('node'))
        labels = [n for n in nodes if n.get('package') == PACKAGE and
                  re.fullmatch(r'(?:\[SharedUID\]\s*)?Shell(?:\s*\(2000\))?',
                               n.get('text', ''), re.IGNORECASE)]
        switches = [n for n in nodes if n.get('package') == PACKAGE and
                    n.get('class') in ('android.widget.Switch', 'android.widget.CompoundButton')
                    and n.get('enabled') == 'true']
        if (labels and len(switches) == 1 and center(switches[0]) and
                any(center(label) and abs(center(label)[1] - center(switches[0])[1]) < 120
                    for label in labels)):
            return center(switches[0]), switches[0].get('checked') == 'true'
    return None


class ShellSetup:
    def __init__(self, serial, avd, output, timeout=180, run=subprocess.run,
                 now=time.monotonic, pause=time.sleep):
        self.serial, self.avd = serial, avd
        self.output = Path(output)
        self.run, self.now, self.pause = run, now, pause
        self.deadline = now() + timeout
        self.last_probe = None

    def command(self, *args, limit=12):
        remaining = self.deadline - self.now()
        if remaining <= 0:
            raise TimeoutError('Shell setup deadline reached')
        return self.run(['adb', '-s', self.serial, *args], capture_output=True,
                        timeout=min(limit, remaining))

    def checked(self, *args, limit=12):
        result = self.command(*args, limit=limit)
        if result.returncode:
            message = result.stderr.decode(errors='replace')
            if any(s in message.lower() for s in ('device offline', 'not found', 'no devices')):
                raise ConnectionError('Device disconnected: ' + message.strip())
            raise RuntimeError(message.strip() or 'ADB command failed')
        return result.stdout.decode(errors='replace')

    def identity(self):
        actual = self.checked('shell', 'getprop ro.boot.qemu.avd_name').strip()
        if actual != self.avd:
            raise ConnectionError('AVD identity changed; refusing to continue')

    def ui(self):
        self.checked('shell', 'timeout 8 uiautomator dump --compressed /data/local/tmp/s25-su-ui.xml')
        xml = self.checked('shell', 'cat /data/local/tmp/s25-su-ui.xml')
        ET.fromstring(xml)
        return xml

    def open_manager(self):
        self.identity()
        self.checked('shell', 'input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard')
        self.checked('shell', 'monkey', '-p', PACKAGE, '-c', 'android.intent.category.LAUNCHER', '1')
        for _ in range(3):
            xml = self.ui()
            if any(n.get('package') == PACKAGE for n in ET.fromstring(xml).iter('node')):
                return
            self.pause(1)
        raise RuntimeError('Magisk manager did not become visible')

    def probe(self):
        # Avoid refreshing Magisk's three-second permission cache on rapid retries.
        if self.last_probe is not None:
            self.pause(max(0, 4 - (self.now() - self.last_probe)))
        self.identity()
        try:
            result = self.command('shell', 'timeout 35 su -c "id -u"', limit=38)
        except subprocess.TimeoutExpired:
            return 'timed_out'
        finally:
            self.last_probe = self.now()
        output = result.stdout.decode(errors='replace').strip()
        error = result.stderr.decode(errors='replace').lower()
        if any(s in error for s in ('device offline', 'not found', 'no devices')):
            raise ConnectionError('Device disconnected during root request')
        if result.returncode == 0 and output == '0':
            return 'allowed'
        if result.returncode in (124, 137):
            return 'timed_out'
        if result.returncode in (1, 13) and any(s in (error + output.lower()) for s in ('denied', 'permission')):
            return 'denied'
        raise RuntimeError(f'Unexpected root response (exit {result.returncode}): {output} {error}')

    def enable_shell(self):
        xml = self.ui()
        for node in ET.fromstring(xml).iter('node'):
            if node.get('package') == PACKAGE and node.get('content-desc') == 'Superuser' and center(node):
                self.checked('shell', 'input', 'tap', *map(str, center(node)))
                break
        for _ in range(3):
            toggle = shell_toggle(self.ui())
            if toggle:
                point, enabled = toggle
                if not enabled:
                    self.checked('shell', 'input', 'tap', *map(str, point))
                return
            self.pause(1)
        raise RuntimeError('Magisk received no visible Shell policy entry; manual permission review required')

    def diagnostics(self, reason, attempt):
        # Diagnostics have a separate, bounded budget even if setup exhausted its deadline.
        folder = self.output / f'attempt-{attempt}'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'status.json').write_text(json.dumps({'reason': reason, 'serial': self.serial,
                                                       'avd': self.avd}, indent=2))
        commands = [('processes.txt', ['shell', 'ps -A']),
                    ('magisk-log.txt', ['logcat', '-d', '-s', 'Magisk']),
                    ('screen.png', ['exec-out', 'screencap', '-p']),
                    ('ui.xml', ['shell', 'timeout 8 uiautomator dump --compressed /data/local/tmp/s25-su-diag.xml >/dev/null && cat /data/local/tmp/s25-su-diag.xml'])]
        for name, args in commands:
            try:
                result = self.run(['adb', '-s', self.serial, *args], capture_output=True, timeout=10)
                (folder / name).write_bytes(result.stdout)
                if result.returncode:
                    (folder / (name + '.error')).write_bytes(result.stderr)
            except (subprocess.SubprocessError, OSError) as error:
                (folder / (name + '.error')).write_text(str(error))
        print(f'Shell diagnostics saved: {folder}', flush=True)

    def complete(self):
        for attempt in (1, 2):
            self.open_manager()
            status = self.probe()
            print(f'Shell request {attempt}/2: {status}', flush=True)
            if status == 'denied':
                self.enable_shell()
                status = self.probe()
            if status == 'allowed':
                print('Shell root verified: fresh request returned UID 0.', flush=True)
                return
            self.diagnostics(status, attempt)
            if attempt == 1:
                # Device-side timeout ends our su client. Do not queue another
                # request blindly or reboot/kill the daemon and other clients.
                print('One recovery attempt: restarting the Magisk manager.', flush=True)
                self.checked('shell', 'am', 'force-stop', PACKAGE)
            else:
                raise RuntimeError('Magisk root requests still time out after manager recovery')


def wait_for_root(serial, timeout=30, call=adb_call, now=time.monotonic, pause=time.sleep):
    deadline = now() + timeout
    # Magisk v30.6 caches SuInfo for three seconds and refreshes its timestamp
    # on every request, including denials. Never poll inside that interval.
    while now() + 4 < deadline:
        pause(4)
        try:
            if call(serial, 'shell', 'su -c "id -u"').strip() == '0':
                return True
        except (subprocess.SubprocessError, OSError):
            pass
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--avd')
    parser.add_argument('--output')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if not args.avd:
        parser.error('--avd is required to verify the target identity')
    if not args.verify_only and not args.output:
        parser.error('--output is required for failure diagnostics')
    setup = ShellSetup(args.serial, args.avd, args.output or '.', args.timeout)
    try:
        if args.verify_only:
            return 0 if setup.probe() == 'allowed' else 1
        setup.complete()
        return 0
    except (RuntimeError, TimeoutError, ConnectionError, subprocess.SubprocessError,
            OSError, ET.ParseError) as error:
        if not args.verify_only:
            setup.diagnostics(str(error), 'failure')
        print(f'Shell setup failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
