import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class LabTests(unittest.TestCase):
    def test_shell_grant_verification_allows_negative_cache_to_expire(self):
        helper = module('setup_su')
        elapsed = [0]
        last_request = [0]
        requests = []
        def pause(seconds):
            elapsed[0] += seconds
        def call(serial, *args):
            age = elapsed[0] - last_request[0]
            last_request[0] = elapsed[0]
            requests.append(elapsed[0])
            if age < 3:
                raise subprocess.CalledProcessError(1, 'su')
            return '0\r\n'
        self.assertTrue(helper.wait_for_root('emulator-test', call=call, now=lambda: elapsed[0], pause=pause))
        self.assertEqual(requests, [4])
        elapsed[0] = 0
        requests.clear()
        def deny(serial, *args):
            requests.append(elapsed[0])
            raise subprocess.CalledProcessError(1, 'su')
        self.assertFalse(helper.wait_for_root('emulator-test', timeout=15, call=deny,
                                             now=lambda: elapsed[0], pause=pause))
        self.assertEqual(requests, [4, 8, 12])

    def test_root_isolation_requires_verified_zygisk_before_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory)/'trace'
            wrapper = r'''
id() { echo 0; }
pm() { echo package:/data/app/checker/base.apk; }
ps() { echo dev.emulab.devicecheck:worker; }
am() { printf '%s\n' "$*" >> "$TRACE"; }
magisk() {
  printf '%s\n' "$*" >> "$TRACE"
  case "$1:$2" in
    --sqlite:SELECT*) echo "value=$ZYGISK_VALUE" ;;
    --denylist:ls) echo 'dev.emulab.devicecheck|dev.emulab.devicecheck' ;;
  esac
  return 0
}
source "$SERVICE" dev.emulab.devicecheck
'''
            env = dict(os.environ, SERVICE=str(ROOT/'device_root_isolation.sh'), TRACE=str(trace), ZYGISK_VALUE='1')
            result = subprocess.run(['/bin/bash'], input=wrapper, text=True, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = trace.read_text()
            self.assertIn("VALUES ('zygisk',1)", commands)
            self.assertIn('--denylist add dev.emulab.devicecheck dev.emulab.devicecheck:worker', commands)
            self.assertIn('--denylist enable', commands)
            self.assertIn('force-stop dev.emulab.devicecheck', commands)
            self.assertIn('reboot required', result.stdout)
            trace.write_text('')
            env['ZYGISK_VALUE'] = '0'
            result = subprocess.run(['/bin/bash'], input=wrapper, text=True, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('--denylist enable', trace.read_text())

    def test_magisk_setup_retries_a_dropped_tap_and_verifies_reboot(self):
        helper = module('setup_magisk')
        dialog = '<hierarchy><node package="com.topjohnwu.magisk" text="Requires additional setup"/><node package="com.topjohnwu.magisk" text="OK" enabled="true" clickable="true" bounds="[775,1253][1006,1379]"/></hierarchy>'
        self.assertEqual(helper.setup_ok_center(dialog), (890, 1316))
        self.assertIsNone(helper.setup_ok_center(dialog.replace('Requires additional setup', 'Unrelated dialog')))
        elapsed = [0]
        taps = []
        def call(serial, *args):
            if args[:3] == ('shell', 'input', 'tap'):
                taps.append(args)
                return ''
            return ('newboot\n1\nready\nTestPhone\n' if len(taps) >= 2 else
                    'oldboot\n1\nincomplete\nTestPhone\n')
        def pause(seconds):
            elapsed[0] += seconds
        helper.complete_setup('emulator-test', 'TestPhone', timeout=30, call=call,
                              read=lambda *a, **kw: dialog, now=lambda: elapsed[0], pause=pause)
        self.assertEqual(len(taps), 2)
        self.assertTrue(all(tap[-2:] == ('890', '1316') for tap in taps))

    def test_magisk_setup_does_not_treat_disappearing_dialog_as_success(self):
        helper = module('setup_magisk')
        elapsed = [0]
        def pause(seconds):
            elapsed[0] += seconds
        def call(serial, *args):
            return 'oldboot\n1\nincomplete\nTestPhone\n'
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            helper.complete_setup('emulator-test', 'TestPhone', timeout=10, call=call,
                                  read=lambda *a, **kw: '<hierarchy/>',
                                  now=lambda: elapsed[0], pause=pause)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            helper.complete_setup('emulator-test', 'OtherPhone', call=call)

    def test_setup_ui_recovers_only_android_anr_wait(self):
        ui = module('setup_ui')
        anr = '<hierarchy><node package="android" resource-id="android:id/aerr_wait" enabled="true" bounds="[70,1268][1010,1394]" /></hierarchy>'
        normal = '<hierarchy><node package="com.topjohnwu.magisk" text="Requires additional setup" /></hierarchy>'
        calls = []
        dumps = iter([anr, normal])
        def adb(serial, *args):
            calls.append((serial, args))
            return next(dumps) if len(args) == 2 else ''
        result = ui.read_ui('emulator-test', call=adb, pause=lambda _: None)
        self.assertEqual(result, normal)
        self.assertIn(('emulator-test', ('shell', 'input', 'tap', '540', '1331')), calls)
        for xml in ('invalid XML', anr.replace('package="android"', 'package="some.app"'), anr.replace('aerr_wait', 'aerr_close'), anr.replace('enabled="true"', 'enabled="false"')):
            self.assertIsNone(ui.anr_wait_center(xml))
        calls.clear()
        result = ui.read_ui('emulator-test', call=lambda serial, *args: calls.append(args) or anr, pause=lambda _: None)
        self.assertEqual(result, '')
        self.assertEqual(sum(args[:3] == ('shell', 'input', 'tap') for args in calls), 2)

    def test_setup_ui_adb_commands_have_host_timeout(self):
        ui = module('setup_ui')
        with patch.object(ui.subprocess, 'run', side_effect=subprocess.TimeoutExpired('adb', 12)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                ui.adb_call('emulator-test', 'shell', 'test')
            self.assertEqual(run.call_args.kwargs['timeout'], 12)

    def test_file_provisioning_stages_protected_libraries_and_rejects_bad_layout(self):
        # A minimal AArch64 ELF containing both device paths in .rodata.
        data = bytearray(2048)
        data[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', data, 18, 183)
        struct.pack_into('<Q', data, 40, 64)
        struct.pack_into('<HHH', data, 58, 64, 3, 1)
        names = b'\0.shstrtab\0.rodata\0'
        data[400:400+len(names)] = names
        labels = b'/dev/goldfish_address_space\0/dev/goldfish_sync\0'
        data[1024:1024+len(labels)] = labels
        struct.pack_into('<IIQQQQIIQQ', data, 128, 1, 3, 0, 0, 400, len(names), 0, 0, 1, 0)
        struct.pack_into('<IIQQQQIIQQ', data, 192, names.index(b'.rodata'), 1, 2, 0, 1024, len(labels), 0, 0, 1, 0)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            fixture = directory / 'original.so'
            fixture.write_bytes(data)
            wrapper = r'''
set -u -o pipefail
FILE_ALIASES=1 GRAPHICS_LABELS=0 SERIAL=emulator-test
mkdir -p "$WORK"
LOG="$WORK/test.log"
step() { :; }; ok() { :; }; die() { echo "$*" >&2; exit 1; }
dsu() { printf '%s\n' "$1" >> "$WORK/root-commands"; }
adb() {
  if [ "$3" = pull ]; then
    [ "$4" = /data/local/tmp/s25-alias-original ] || return 1
    cp "$FIXTURE" "$5"
  fi
}
source "$SCRIPT_DIR/provision_file_profiles.sh"
'''
            env = dict(os.environ, WORK=str(directory/'good'), SCRIPT_DIR=str(ROOT), FIXTURE=str(fixture))
            subprocess.run(['/bin/bash'], input=wrapper, text=True, env=env, capture_output=True, check=True)
            commands = (directory/'good/root-commands').read_text()
            self.assertEqual(commands.count('chmod 644 /data/local/tmp/s25-alias-original'), 7)
            self.assertIn('/data/adb/post-fs-data.d/98-s25-file-aliases.sh', commands)
            self.assertIn('magisk --install-module', commands)
            manifest = json.loads((directory/'good/file-aliases/manifest.json').read_text())
            self.assertEqual(len(manifest['binaries']), 7)
            fixture.write_bytes(b'wrong image')
            env['WORK'] = str(directory/'bad')
            result = subprocess.run(['/bin/bash'], input=wrapper, text=True, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            commands = (directory/'bad/root-commands').read_text()
            self.assertNotIn('magisk --install-module', commands)
            self.assertNotIn('/data/adb/post-fs-data.d/', commands)

    def test_setup_random_names_and_existing_name_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, ANDROID_AVD_HOME=directory + '/avds')
            command = ['/bin/bash', str(ROOT / 'setup_galaxy_s25_avd.sh'), '--dry-run', '--yes']
            first = subprocess.run(command, env=env, capture_output=True, text=True, check=True).stdout
            second = subprocess.run(command, env=env, capture_output=True, text=True, check=True).stdout
            self.assertNotEqual(first.splitlines()[0], second.splitlines()[0])
            self.assertIn('File aliases: 1', first)
            self.assertIn('Graphics labels: 1', first)
            self.assertIn('Battery: 1', first)
            self.assertIn('Checker: 1', first)
            self.assertIn('Bumble installation: Google Play', first)
            self.assertIn('no automatic APK/XAPK installation', first)
            skipped = subprocess.run(command + ['--no-apps'], env=env, capture_output=True, text=True, check=True).stdout
            self.assertIn('Bumble installation: Google Play skipped', skipped)
            skipped = subprocess.run(command + ['--no-play-store'], env=env, capture_output=True, text=True, check=True).stdout
            self.assertIn('Bumble installation: Google Play skipped', skipped)
            self.assertEqual(list(Path(directory).iterdir()), [])  # Preview has no writes.
            avds = Path(directory) / 'avds'
            avds.mkdir()
            for suffix in ('.avd', '.ini'):
                existing = avds / ('Taken' + suffix)
                existing.write_text('keep me')
                result = subprocess.run(command + ['--name', 'Taken'], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(existing.read_text(), 'keep me')
                existing.unlink()
            backup = Path(directory) / 'galaxy_s25_avd_backups/Taken'
            backup.mkdir(parents=True)
            result = subprocess.run(command + ['--name', 'Taken'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_setup_interactive_answers_and_input_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, ANDROID_AVD_HOME=directory + '/avds')
            command = ['/bin/bash', str(ROOT / 'setup_galaxy_s25_avd.sh'), '--dry-run']
            result = subprocess.run(command + ['--interactive'], input='My_New_Phone\n6144\n6\n120\nAlex\nNonbinary\n', env=env, capture_output=True, text=True, check=True)
            self.assertIn('AVD name: My_New_Phone', result.stdout)
            self.assertIn('Android Studio display name: My New Phone', result.stdout)
            self.assertIn('RAM: 6144 MB', result.stdout)
            self.assertIn('Cores: 6', result.stdout)
            self.assertIn('Bumble profile name: Alex', result.stdout)
            self.assertIn('Bumble profile gender: Nonbinary', result.stdout)
            self.assertIn('Phone number: requested only at Bumble phone entry', result.stdout)
            for options in (['--name', '..'], ['--name', 'bad/name'], ['--ram', 'oops'], ['--cores', '0'], ['--vsync', '999']):
                result = subprocess.run(command + ['--yes'] + options, env=env, capture_output=True)
                self.assertEqual(result.returncode, 2, options)
            result = subprocess.run(command + ['--non-interactive', '--keep-file-paths'], env=env, capture_output=True, text=True, check=True)
            self.assertIn('File aliases: 0', result.stdout)
            self.assertIn('Graphics labels: 0', result.stdout)
            camera = subprocess.run(command + ['--yes', '--front-camera', 'webcam1'], env=env, capture_output=True, text=True, check=True)
            self.assertIn('Front camera: webcam1', camera.stdout)
            camera = subprocess.run(command + ['--yes', '--front-camera', 'invalid'], env=env, capture_output=True, text=True)
            self.assertEqual(camera.returncode, 2)

    def test_camera_media_validation_handles_relative_paths_spaces_and_bad_files(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            env = dict(os.environ, HOME=str(directory), ANDROID_AVD_HOME=str(directory / 'avds'))
            command = ['/bin/bash', str(ROOT / 'setup_galaxy_s25_avd.sh'), '--dry-run', '--yes']
            media = directory / 'phone recording.mp4'
            media.write_bytes(b'camera fixture')
            for mode in ('videofile', 'imagefile'):
                result = subprocess.run(command + ['--front-camera', mode + ':' + media.name],
                                        cwd=directory, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Front camera: {mode}:{media.resolve()}', result.stdout)
            empty = directory / 'empty.mp4'
            empty.touch()
            newline = directory / 'bad\npath.mp4'
            newline.write_bytes(b'camera fixture')
            for path in (directory, directory / 'missing.mp4', empty, newline):
                result = subprocess.run(command + ['--front-camera', 'videofile:' + str(path)],
                                        cwd=directory, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, path)
                self.assertIn('Camera media must be', result.stderr)
            self.assertFalse((directory / 'avds').exists())

    def test_sensor_patch_only_changes_readonly_labels(self):
        patcher = module("patch_sensor_labels")
        data = bytearray(4096)
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, 183)
        struct.pack_into("<Q", data, 40, 64)
        struct.pack_into("<HHH", data, 58, 64, 4, 1)
        names = b"\0.shstrtab\0.rodata\0.text\0"
        data[400:400+len(names)] = names
        labels = b"\0".join(b"Goldfish Sensor " + str(i).encode() for i in range(12)) + b"\0The Android Open Source Project\0"
        data[1024:1024+len(labels)] = labels
        code = bytes(range(128))
        data[512:640] = code
        struct.pack_into("<IIQQQQIIQQ", data, 128, names.index(b".shstrtab"), 3, 0, 0, 400, len(names), 0, 0, 1, 0)
        struct.pack_into("<IIQQQQIIQQ", data, 192, names.index(b".rodata"), 1, 2, 0, 1024, len(labels), 0, 0, 1, 0)
        struct.pack_into("<IIQQQQIIQQ", data, 256, names.index(b".text"), 1, 6, 0, 512, len(code), 0, 0, 4, 0)
        original = bytes(data)
        patched, manifest = patcher.patch_labels(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched[:1024], original[:1024])
        self.assertEqual(patched[1024+len(labels):], original[1024+len(labels):])
        self.assertNotIn(b"Goldfish ", patched[1024:1024+len(labels)])
        self.assertEqual(manifest["sensor_label_prefixes"], 12)
        with self.assertRaises(ValueError):
            patcher.patch_labels(patched)  # No silent double patching.
        bad = bytearray(original)
        struct.pack_into("<Q", bad, 192+8, 6)  # An executable region must be refused.
        with self.assertRaises(ValueError):
            patcher.patch_labels(bytes(bad))

    def test_qemu_partial_failure_restores_both_values(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "ro.kernel.qemu").write_text("1")
            (directory / "ro.boot.qemu").write_text("1")
            wrapper = r'''
getprop() { if [ "$1" = sys.boot_completed ]; then echo 1; else cat "$S25_LAB_DIR/$1"; fi; }
magisk() { if [ "$3" = ro.boot.qemu ] && [ "$4" = 0 ]; then return 1; fi; printf '%s' "$4" > "$S25_LAB_DIR/$3"; }
source "$SERVICE"
'''
            env = dict(os.environ, S25_LAB_DIR=str(directory), SERVICE=str(ROOT / "device_qemu_profile.sh"))
            result = subprocess.run(["bash"], input=wrapper, text=True, env=env, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((directory / "ro.kernel.qemu").read_text(), "1")
            self.assertEqual((directory / "ro.boot.qemu").read_text(), "1")

    def test_device_profiles_are_distinct_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            for name in ("Device_A", "Device_B"):
                destination = Path(directory) / name
                command = ["python3", "-I", str(ROOT / "generate_lab_profile.py"), "--name", name, "--output-dir", str(destination)]
                subprocess.run(command, check=True, capture_output=True)
                commands.append(command)
            a = Path(directory) / "Device_A/device-profile.json"
            before = a.read_bytes()
            other = json.loads((Path(directory) / "Device_B/device-profile.json").read_text())
            self.assertNotEqual(json.loads(before)["seed"], other["seed"])
            retry = subprocess.run(commands[0], capture_output=True)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(a.read_bytes(), before)

    def test_temperature_drift_and_discharge_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "battery.conf").write_text("LEVEL=77\nTEMP=273\nFULL_CHARGE_UAH=3853000\nDRAIN_TICKS=8\nTICKS=0\n")
            wrapper = r'''
getprop() { echo 1; }
dumpsys() { printf '%s\n' "$*" >> "$TRACE"; }
sleep() { iteration=$((iteration + 1)); if [ "$iteration" -ge 100 ]; then touch "$D/battery.disabled"; fi; }
iteration=0
source "$SERVICE"
'''
            env = dict(os.environ, S25_BATTERY_DIR=str(directory), TRACE=str(directory / "trace"), SERVICE=str(ROOT / "device_battery_service.sh"))
            subprocess.run(["bash"], input=wrapper, text=True, env=env, check=True, timeout=10)
            trace = (directory / "trace").read_text().splitlines()
            levels = [int(line.rsplit(" ", 1)[1]) for line in trace if line.startswith("battery set -f level")]
            temperatures = [int(line.rsplit(" ", 1)[1]) for line in trace if line.startswith("battery set temp")]
            self.assertEqual(levels[0], 77)
            self.assertEqual(levels[95], 77)  # 8 minutes at a five-second cadence
            self.assertEqual(levels[96], 76)
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(temperatures, temperatures[1:])))
            self.assertEqual(trace[-1], "battery reset")

    def test_battery_failure_resets_framework_override(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "battery.conf").write_text("LEVEL=77\nTEMP=273\nFULL_CHARGE_UAH=3853000\nDRAIN_TICKS=8\nTICKS=0\n")
            wrapper = r'''
getprop() { echo 1; }
dumpsys() { printf '%s\n' "$*" >> "$TRACE"; [ "$*" != 'battery set temp 273' ]; }
source "$SERVICE" --once
'''
            env = dict(os.environ, S25_BATTERY_DIR=str(directory), TRACE=str(directory / "trace"), SERVICE=str(ROOT / "device_battery_service.sh"))
            result = subprocess.run(["bash"], input=wrapper, text=True, env=env, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((directory / "trace").read_text().endswith("battery reset\n"))

    def test_signal_walk_has_small_steps_and_stays_in_range(self):
        signal = module("emulator_signal_sim")
        rng = random.Random(42)
        value = 21
        for _ in range(2000):
            new = signal.next_rssi(rng, value, 21)
            self.assertLessEqual(abs(new - value), 1)
            self.assertTrue(14 <= new <= 29)
            self.assertTrue(1 <= signal.signal_profile(new) <= 4)
            value = new

    def test_build_fields_match_fingerprint(self):
        prefix = (ROOT / "galaxy_s25_avd_lab.sh").read_text().split("# ── UI", 1)[0]
        result = subprocess.run(["bash"], input=prefix + "\nprofile_props 15\n", text=True, capture_output=True, check=True)
        props = dict(line.split("=", 1) for line in result.stdout.splitlines())
        fingerprint = props["ro.build.fingerprint"].split("/")
        self.assertEqual(fingerprint[3], props["ro.build.id"])
        self.assertEqual(fingerprint[4].split(":")[0], props["ro.build.version.incremental"])
        self.assertEqual(props["ro.hardware"], "sun")
        for selector in ("ro.boot.hardware", "ro.hardware.egl", "ro.hardware.gralloc", "ro.hardware.power", "ro.hardware.vulkan"):
            self.assertNotIn(selector, props)
        self.assertNotIn("ro.kernel.qemu", props)


if __name__ == "__main__":
    unittest.main()
