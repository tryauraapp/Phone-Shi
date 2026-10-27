#!/usr/bin/env python3
"""Swap the front-camera clip of one specific phone, then relaunch it.

    python3 swap_camera_video.py --status                      # every lab phone's clip
    python3 swap_camera_video.py --avd NAME --video clip.mp4   # closed phone: set and launch
    python3 swap_camera_video.py --avd NAME --video clip.mp4 --restart   # close a running phone first
    python3 swap_camera_video.py --avd NAME --video clip.mp4 --face-track --restart

The emulator reads the camera source when the phone starts, so a swap always
means a cold restart of that one phone. Clips already prepared for a phone are
cached by checksum, so switching back to an earlier clip does not re-encode.
Other phones are never touched.

--face-track runs face_track_video.py on the source clip first (requires the
.venv with mediapipe/opencv).  The face-tracked intermediate is cached next to
the original inside the phone's camera/ directory.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location('_swap_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lab_phones(env):
    home = Path(env.get('ANDROID_AVD_HOME') or Path.home() / '.android/avd')
    return sorted(path.stem for path in home.glob('*.ini') if (home / (path.stem + '.avd')).is_dir())


def phone_status(name, env, native):
    directory = native.avd_directory(name, env)
    record = directory / 'camera/native-camera.json'
    config = directory / 'config.ini'
    values = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line) if config.is_file() else {}
    front = values.get('hw.camera.front', '').strip()
    status = {'avd': name, 'front': front, 'clip': None, 'prepared': None, 'state': None, 'running': None}
    if record.is_file():
        data = json.loads(record.read_text())
        status.update(clip=data.get('original'), prepared=data.get('prepared_video'),
                      state=data.get('status'), fps=data.get('fps'), source_sha256=data.get('source_sha256'))
    elif front.startswith('videofile:'):
        status['clip'] = front[len('videofile:'):]
        status['state'] = 'legacy_direct_videofile'
    try:
        status['running'] = native.running_serial(name)
    except ValueError:
        status['running'] = 'unknown'
    return status


def last_json(text):
    """The configurator echoes the preparer's record before its own; keep the last."""
    decoder, index, record = json.JSONDecoder(), 0, None
    while True:
        start = text.find('{', index)
        if start < 0:
            break
        record, index = decoder.raw_decode(text, start)
    if record is None:
        raise ValueError('no JSON record in configurator output')
    return record


def close_phone(serial, directory, native, adb='adb', timeout=90):
    subprocess.run([adb, '-s', serial, 'emu', 'kill'], check=False, timeout=20,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = subprocess.check_output([adb, 'devices'], timeout=10).decode()
        if serial not in listing and not native.has_live_lock(directory):
            return True
        time.sleep(1)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--avd', help='the one phone to change')
    parser.add_argument('--video', type=Path, help='new clip (any ffmpeg-readable file)')
    parser.add_argument('--preview-size', default='1080x1440', help='app preview size, default S25 3:4')
    parser.add_argument('--fps', type=float, default=30.0, help='emulated camera frame rate')
    parser.add_argument('--hflip', action='store_true', help='horizontally mirror the source video')
    parser.add_argument('--restart', action='store_true', help='close the phone first if it is running')
    parser.add_argument('--no-launch', action='store_true', help='only save the clip; do not start the phone')
    parser.add_argument('--face-track', action='store_true',
                        help='run face tracking to center the face for app oval verification; '
                             'requires .venv with mediapipe and opencv')
    parser.add_argument('--face-target-y', type=float, default=0.38,
                        help='vertical face position for --face-track (0=top, 1=bottom; default 0.38)')
    parser.add_argument('--face-fill', type=float, default=0.55,
                        help='face width as fraction of frame for --face-track (default 0.55)')
    parser.add_argument('--status', action='store_true', help='print each lab phone\'s current clip and exit')
    args = parser.parse_args(argv)
    env = dict(os.environ)
    native = sibling('native_video_camera')
    if args.status:
        names = [args.avd] if args.avd else lab_phones(env)
        for name in names:
            print(json.dumps(phone_status(name, env, native)))
        return 0
    if not args.avd or not args.video:
        parser.error('--avd and --video are required to swap (or use --status)')
    video = args.video.expanduser().resolve()
    if not video.is_file():
        parser.error(f'clip not found: {video}')
    directory = native.avd_directory(args.avd, env)
    if not (directory / 'config.ini').is_file():
        parser.error(f'no such phone: {args.avd}')
    serial = native.running_serial(args.avd)
    if serial or native.has_live_lock(directory):
        if not args.restart:
            parser.exit(2, f'{args.avd} is running on {serial or "this Mac"}. Close it, or pass --restart to close it now.\n')
        print(f'Closing {args.avd} ({serial}) ...', flush=True)
        if not close_phone(serial, directory, native):
            parser.exit(2, f'{args.avd} did not close; nothing changed.\n')
    if args.face_track:
        venv_python = ROOT / '.venv' / 'bin' / 'python3'
        if not venv_python.is_file():
            parser.exit(2, f'.venv not found at {venv_python}; create it with:\n'
                           '  python3 -m venv .venv && .venv/bin/pip install mediapipe opencv-python-headless\n')
        import hashlib as _hl
        source_hash = _hl.sha256(video.read_bytes()).hexdigest()[:16]
        tracked_name = f'face-tracked-{source_hash}.mp4'
        tracked_path = directory / 'camera' / tracked_name
        if tracked_path.exists():
            print(f'Reusing cached face-tracked clip: {tracked_path.name}', flush=True)
        else:
            print(f'Face-tracking {video.name} ...', flush=True)
            ft_result = subprocess.run([
                str(venv_python), str(ROOT / 'face_track_video.py'),
                str(video), str(tracked_path),
                '--target-y', str(args.face_target_y),
                '--face-fill', str(args.face_fill),
            ], capture_output=True, text=True)
            sys.stdout.write(ft_result.stdout)
            if ft_result.returncode:
                sys.stderr.write(ft_result.stderr)
                parser.exit(2, 'Face tracking failed; the phone is unchanged.\n')
        video = tracked_path

    print(f'Preparing {video.name} for {args.avd} ...', flush=True)
    cfg_cmd = [sys.executable, '-I', str(ROOT / 'configure_video_camera.py'), '--avd', args.avd,
               '--video', str(video), '--preview-size', args.preview_size, '--fps', str(args.fps)]
    if args.hflip:
        cfg_cmd.append('--hflip')
    result = subprocess.run(cfg_cmd, capture_output=True, text=True)
    if result.returncode:
        sys.stderr.write(result.stderr)
        parser.exit(2, f'Could not prepare the clip for {args.avd}; its previous clip is unchanged.\n')
    record = last_json(result.stdout)
    print(f'Saved: {record["prepared_video"]}', flush=True)
    if args.no_launch:
        return 0
    launcher = [sys.executable, '-I', str(ROOT / 'emulator_proxy.py'), '--avd', args.avd,
                '--check-video-camera', '--camera-viewer']
    print('Launching ' + args.avd + ' with the new clip ...', flush=True)
    os.execv(sys.executable, launcher)


if __name__ == '__main__':
    sys.exit(main())
