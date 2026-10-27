#!/usr/bin/env python3
"""Build a local-only Camera2 frame probe and test the specifically named AVD."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

PACKAGE = 'ai.phoneshi.cameraprobe'


def run(command, **kwargs):
    return subprocess.run([str(item) for item in command], check=True, timeout=120, **kwargs)


def revision(path):
    return tuple(map(int, re.findall(r'\d+', path.name)))


def motion_summary(rows):
    hashes = {row['sha256'] for row in rows}
    times = [row.get('captured_elapsed_ns', row['timestamp_ns']) for row in rows]
    span = (max(times) - min(times)) / 1e9 if times else 0
    middle = (max(times) + min(times)) / 2 if times else 0
    early = {row['sha256'] for row, timestamp in zip(rows, times) if timestamp <= middle}
    late = {row['sha256'] for row, timestamp in zip(rows, times) if timestamp > middle}
    updates = [row.get('consumer_updates') for row in rows]
    consumer_fps = ((updates[-1] - updates[0]) / span if span and updates
                    and all(isinstance(value, int) for value in (updates[0], updates[-1]))
                    and updates[-1] >= updates[0] else None)
    return {'frames': len(rows), 'distinct_pixel_samples': len(hashes),
            'observed_span_seconds': round(span, 3),
            'consumer_updates_per_second': round(consumer_fps, 3) if consumer_fps is not None else None,
            'motion_verified': span >= 4 and len(hashes) >= 3 and len(early) >= 2 and len(late) >= 2}


def build_apk(sdk, output):
    tools = max((sdk / 'build-tools').iterdir(), key=revision)
    platform = max((sdk / 'platforms').iterdir(), key=revision) / 'android.jar'
    java = Path(os.environ.get('JAVA_HOME') or '/Applications/Android Studio.app/Contents/jbr/Contents/Home')
    env = dict(os.environ, JAVA_HOME=str(java))
    source = Path(__file__).resolve().parent
    project = source.parent
    key = project / '.local/camera-probe-signing/debug.keystore'
    key.parent.mkdir(parents=True, exist_ok=True)
    if not key.exists():
        # Retain the original local probe identity across different evidence
        # directories; never uninstall the app to work around a signing error.
        previous = list((project / '.local').glob('camera-probe*/debug.keystore'))
        if previous:
            shutil.copy2(min(previous, key=lambda item: item.stat().st_mtime), key)
        else:
            run([java / 'bin/keytool', '-genkeypair', '-keystore', key, '-alias', 'androiddebugkey',
                 '-storepass', 'android', '-keypass', 'android', '-dname', 'CN=CameraProbe',
                 '-keyalg', 'RSA', '-validity', '3650'])
    version = hashlib.sha256(b''.join(path.read_bytes() for path in
        (source / 'CameraProbe.java', source / 'AndroidManifest.xml', Path(__file__), key))
        + str(platform).encode() + str(tools).encode()).hexdigest()[:16]
    apk, stamp = output / 'camera-probe.apk', output / 'build.json'
    if apk.exists() and stamp.exists() and json.loads(stamp.read_text()).get('version') == version:
        return apk, version
    classes, dex = output / 'classes', output / 'dex'
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    run([java / 'bin/javac', '-source', '8', '-target', '8', '-classpath', platform,
         '-d', classes, source / 'CameraProbe.java'], env=env)
    run([tools / 'd8', '--lib', platform, '--min-api', '23', '--output', dex,
         *classes.rglob('*.class')], env=env)
    unsigned = output / 'unsigned.apk'
    run([tools / 'aapt2', 'link', '--manifest', source / 'AndroidManifest.xml',
         '-I', platform, '--min-sdk-version', '23', '--target-sdk-version', '35',
         '--version-code', '1', '--version-name', version, '-o', unsigned])
    with zipfile.ZipFile(unsigned, 'a') as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
    aligned, apk = output / 'aligned.apk', output / 'camera-probe.apk'
    run([tools / 'zipalign', '-f', '4', unsigned, aligned])
    run([tools / 'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:android',
         '--out', apk, aligned], env=env)
    stamp.write_text(json.dumps({'version': version}) + '\n')
    return apk, version


def locate_serial(sdk, avd, serial=None, timeout=180):
    deadline = time.monotonic() + timeout
    adb = str(sdk / 'platform-tools/adb')
    while time.monotonic() < deadline:
        listing = subprocess.check_output([adb, 'devices'], timeout=10).decode()
        for line in listing.splitlines()[1:]:
            parts = line.split()
            if len(parts) != 2 or parts[1] != 'device' or not parts[0].startswith('emulator-'):
                continue
            if serial and serial != parts[0]:
                continue
            try:
                name = subprocess.check_output([adb, '-s', parts[0], 'emu', 'avd', 'name'], timeout=10).decode().splitlines()[0].strip()
                ready = subprocess.check_output([adb, '-s', parts[0], 'shell', 'getprop', 'sys.boot_completed'], timeout=10).strip()
                if name == avd and ready == b'1':
                    return parts[0]
            except subprocess.SubprocessError:
                pass
        time.sleep(2)
    raise RuntimeError('Timed out waiting for the named AVD to boot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial')
    parser.add_argument('--avd', required=True)
    parser.add_argument('--seconds', type=float, default=22)
    parser.add_argument('--capture-size', default='640x480', choices=['640x480', '1280x960'])
    parser.add_argument('--mode', default='yuv', choices=['yuv', 'texture'],
                        help='yuv: CPU ImageReader frames; texture: SurfaceTexture preview like real apps')
    parser.add_argument('--keep-preview', action='store_true',
                        help='Leave the real front-camera viewer open after the test')
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / '.local/camera-probe')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 600:
        parser.error('sample between five and 600 seconds')
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or Path.home() / 'Library/Android/sdk')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'report.json').write_text(json.dumps({'avd': args.avd, 'status': 'checking',
                                                   'motion_verified': False}) + '\n')
    apk, version = build_apk(sdk, output)
    args.serial = locate_serial(sdk, args.avd, args.serial)

    adb_base = [sdk / 'platform-tools/adb', '-s', args.serial]

    def adb(*command):
        return subprocess.check_output([str(x) for x in [*adb_base, *command]], timeout=30)

    def identity():
        actual = adb('emu', 'avd', 'name').decode().splitlines()[0].strip()
        if actual != args.avd:
            raise RuntimeError('AVD identity mismatch; refusing to mutate another phone')

    identity()
    installed = adb('shell', 'dumpsys', 'package', PACKAGE).decode()
    if not re.search(r'versionName=' + re.escape(version) + r'\b', installed):
        run([*adb_base, 'install', '--no-streaming', '-r', apk])
    identity()
    adb('shell', 'pm', 'grant', PACKAGE, 'android.permission.CAMERA')
    adb('shell', 'am', 'force-stop', 'com.android.camera2')
    adb('shell', 'am', 'force-stop', PACKAGE)
    width, height = map(int, args.capture_size.split('x'))
    adb('shell', 'am', 'start', '-n', PACKAGE + '/.CameraProbe', '--el', 'sample_ms', str(int(args.seconds * 1000)),
        '--ei', 'capture_width', str(width), '--ei', 'capture_height', str(height), '--es', 'mode', args.mode)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        identity()
        raw = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/frames.jsonl')
        (output / 'frames.jsonl').write_bytes(raw)
        rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        summary = motion_summary(rows)
        report = {'avd': args.avd, 'serial': args.serial, **summary, 'mode': args.mode,
                  'status': 'passed' if summary['motion_verified'] else 'failed', 'capture_size': [width, height],
                  'consumer_updates': rows[-1].get('consumer_updates') if rows else None,
                  'note': ('SurfaceTexture preview pixels read back from the on-screen texture.' if args.mode == 'texture'
                           else 'Direct front Camera2 ImageReader pixels, not screenshot/UI motion.')}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        for number in ([1, 11] if len(rows) >= 11 else [1]) if rows else ():
            pgm = adb('exec-out', 'run-as', PACKAGE, 'cat', f'files/frame-{number}.pgm')
            (output / f'frame-{number}.pgm').write_bytes(pgm)
        if rows:
            (output / 'frame-latest.pgm').write_bytes(adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/latest.pgm'))
        print(json.dumps(report, indent=2))
    finally:
        identity()
        if not args.keep_preview:
            adb('shell', 'am', 'force-stop', PACKAGE)
            adb('shell', 'am', 'start', '-a', 'android.media.action.STILL_IMAGE_CAMERA')
    if not report['motion_verified']:
        parser.exit(1, 'Direct camera pixel check FAILED: source frames are not changing.\n')


if __name__ == '__main__':
    main()
