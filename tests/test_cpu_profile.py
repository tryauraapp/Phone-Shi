import os
import json
import re
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CPUProfileTests(unittest.TestCase):
    def test_setup_keeps_real_implementer_and_requires_arm64(self):
        source = (ROOT / 'setup_galaxy_s25_avd.sh').read_text()
        start = source.index('verify_cpu_architecture() {')
        function = source[start:source.index('\n}\n', start) + 3]
        wrapper = '''
SERIAL=emulator-test
CPU_PROFILE_INSTALLED=1
ok() { :; }
warn() { printf 'Warning: %s\\n' "$*"; }
die() { exit 1; }
adb() {
  case "$*" in
    *'getprop ro.product.cpu.abi') printf '%s\\n' "$TEST_ABI" ;;
    *'uname -m') echo aarch64 ;;
    *'cat /proc/cpuinfo') printf 'CPU implementer : 0x61\\n' ;;
  esac
}
'''
        for abi, expected in [('arm64-v8a', 0), ('x86_64', 1)]:
            result = subprocess.run(['bash'], input=wrapper + function + '\nverify_cpu_architecture\n',
                                    env=dict(os.environ, TEST_ABI=abi), text=True, capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected == 0:
                self.assertNotIn('Warning:', result.stdout)

    def test_app_cpu_warning_does_not_bypass_network_verification(self):
        source = (ROOT / 'setup_galaxy_s25_avd.sh').read_text()
        scripts = re.findall(r'''python3 - "\$WORK/checker-report.json" <<'PY'\n(.*?)\nPY''', source, re.S)
        script = next(text for text in scripts if 'Network topology' in text)
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            for transport, expected in [('CELLULAR', 0), ('WIFI', 1)]:
                report.write_text(json.dumps({'findings': [
                    {'name': 'CPU context', 'evidence': 'CPU implementer : 0x61'},
                    {'name': 'Network topology', 'evidence': f'Transport={transport}\nData network=LTE\n10.14.2.100'},
                ]}))
                result = subprocess.run([sys.executable, '-', str(report)], input=script, text=True, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertNotIn('Warning:', result.stdout)

    def run_profile(self, directory, text):
        root = Path(directory)
        cpu = root / 'cpuinfo'
        cpu.write_text(text)
        (root / 'mountinfo').touch()
        env = dict(os.environ, S25_CPUINFO=str(cpu), S25_MOUNTINFO=str(root / 'mountinfo'),
                   S25_LAB_DIR=str(root / 'profile'), SERVICE=str(ROOT / 'device_cpu_profile.sh'))
        wrapper = '''
magisk() { [[ "$1" == --clone-attr ]]; }
mount() { [[ "$1" == --bind ]] && cp "$2" "$3"; }
source "$SERVICE"
'''
        result = subprocess.run(['bash'], input=wrapper, text=True, env=env, capture_output=True)
        return result, cpu.read_text()

    def test_changes_only_implementer_and_keeps_original_backup(self):
        original = 'processor : 0\nCPU implementer : 0x61\nCPU part : 0x022\nFeatures : aes sha1\n\nprocessor : 1\nCPU implementer : 0x61\n'
        with tempfile.TemporaryDirectory() as directory:
            result, actual = self.run_profile(directory, original)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(actual, original.replace('CPU implementer : 0x61', 'CPU implementer : 0x41'))
            self.assertEqual((Path(directory) / 'profile/cpu/original').read_text(), original)

    def test_missing_implementer_fails_without_altering_cpuinfo(self):
        original = 'processor : 0\nFeatures : aes\n'
        with tempfile.TemporaryDirectory() as directory:
            result, actual = self.run_profile(directory, original)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(actual, original)
