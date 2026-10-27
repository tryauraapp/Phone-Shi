#!/usr/bin/env python3
"""Prepare and persist a camera-scoped native video profile on a CLOSED AVD."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location('_camera_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def ini_values(text, values):
    result, done = [], set()
    for line in text.splitlines():
        key = line.split('=', 1)[0].strip()
        if key in values:
            if key not in done:
                result.append(key + '=' + values[key])
                done.add(key)
        else:
            result.append(line)
    result.extend(key + '=' + value for key, value in values.items() if key not in done)
    return '\n'.join(result) + '\n'


def save(path, text):
    if path.exists() and path.read_text() == text:
        return
    backup = path.with_name(path.name + '.before-native-camera-profile')
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    staged = path.with_name(path.name + '.native-camera-new')
    staged.write_text(text)
    if path.exists():
        staged.chmod(path.stat().st_mode & 0o777)
    staged.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd', required=True)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--preview-size', default='1080x1440',
                        help='measured app preview, NOT the phone display; saved S25 default is 3:4')
    parser.add_argument('--vertical-anchor', type=float, default=0.40625)
    parser.add_argument('--preview-method', choices=['camera2_reader', 'stock'], default='camera2_reader')
    parser.add_argument('--fps', type=float, default=30.0,
                        help='emulated phone camera frame rate; the clip is resampled to it (default 30)')
    parser.add_argument('--hflip', action='store_true',
                        help='horizontally mirror the source video before framing')
    args = parser.parse_args()
    native, prepare = sibling('native_video_camera'), sibling('prepare_camera_video')
    directory = native.avd_directory(args.avd, os.environ)
    config = directory / 'config.ini'
    if not config.is_file():
        parser.error('Existing AVD config not found; this tool never creates or wipes a phone')
    identifiers = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line)
    if identifiers.get('AvdId', '').strip() != args.avd:
        parser.error('AVD config identity does not match the selected phone')
    if native.running_serial(args.avd) or native.has_live_lock(directory):
        parser.error('Close this AVD before configuring its camera; no settings have been changed')
    native.reject_experimental_engine(directory)
    source = args.video.expanduser().resolve()
    if not source.is_file():
        parser.error('Input video not found')
    if not shutil.which('ffmpeg'):
        parser.error('ffmpeg is required to prepare native camera media')
    preview = prepare.size(args.preview_size)
    profile = json.loads(prepare.DEFAULT_PROFILE.read_text())
    prepare.framing_filter(preview, profile['canvas_size'], args.vertical_anchor)
    source_sha = digest(source)
    key = hashlib.sha256(json.dumps({'source': source_sha, 'preview': preview,
        'anchor': args.vertical_anchor, 'fps': args.fps, 'hflip': args.hflip, 'profile': profile,
        'preparer': digest(ROOT / 'prepare_camera_video.py')}, sort_keys=True).encode()).hexdigest()[:24]
    folder = directory / 'camera'
    folder.mkdir(exist_ok=True)
    with (folder / '.profile.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = folder / ('original-' + source_sha[:24] + source.suffix)
        output = folder / ('front-' + key + '.webm')
        manifest = output.with_suffix('.webm.json')
        staging = Path(tempfile.mkdtemp(prefix='.native-video-', dir=folder))
        try:
            if not original.exists():
                shutil.copy2(source, staging / 'original')
                if digest(staging / 'original') != source_sha:
                    raise RuntimeError('Source changed during copying; retry with a stable input file')
                (staging / 'original').replace(original)
            elif digest(original) != source_sha:
                raise RuntimeError('Saved original differs from its recorded checksum; refusing to overwrite it')
            if not output.exists():
                staged_video = staging / 'prepared.webm'
                prep_cmd = [os.sys.executable, str(ROOT / 'prepare_camera_video.py'),
                    str(original), str(staged_video), '--codec', 'vp9',
                    '--preview-size', args.preview_size, '--vertical-anchor', str(args.vertical_anchor),
                    '--fps', str(args.fps)]
                if args.hflip:
                    prep_cmd.append('--hflip')
                subprocess.run(prep_cmd, check=True)
                media_record = json.loads(staged_video.with_suffix('.webm.json').read_text())
                media_record['command'][-1] = str(output)
                staged_manifest = staging / 'prepared.json'
                staged_manifest.write_text(json.dumps(media_record, indent=2) + '\n')
                staged_manifest.replace(manifest)
                staged_video.replace(output)
            elif not manifest.is_file():
                raise RuntimeError('Cached media has no preparation manifest; refusing to trust it')
            existing = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line)
            if native.running_serial(args.avd) or native.has_live_lock(directory):
                raise RuntimeError('The AVD started during preparation; close it and rerun to apply settings')
            back = existing.get('hw.camera.back', 'none').strip()
            # Environment is shared by environment/virtualscene cameras. Keep a
            # separate rear placeholder and stable two-camera ordering, not a
            # second copy of the front video or stale Camera-app index.
            if back in ('none', 'virtualscene', 'environment'):
                back = 'emulated'
            environment = directory / 'environment.ini'
            save(environment, ini_values(environment.read_text() if environment.exists() else '',
                {'version': '1', 'scene.mode': 'videofile:' + str(output), 'background.enabled': 'false'}))
            settings = directory / 'AVD.conf'
            save(settings, native.animation_enabled_text(settings.read_text() if settings.exists() else ''))
            save(config, ini_values(config.read_text(), {'hw.camera.front': 'environment', 'hw.camera.back': back}))
            record = {'avd': args.avd, 'original': str(original), 'source_sha256': source_sha,
                'prepared_video': str(output), 'preview_size': list(preview),
                'vertical_anchor': args.vertical_anchor, 'fps': args.fps, 'hflip': args.hflip,
                'backend': 'native_environment',
                'codec': 'vp9', 'background_enabled': False, 'preview_method': args.preview_method,
                'status': 'prepared_not_yet_verified'}
            save(folder / 'native-camera.json', json.dumps(record, indent=2) + '\n')
            print(json.dumps(record, indent=2))
        finally:
            # Only the freshly-created private staging directory is removed.
            shutil.rmtree(staging)


if __name__ == '__main__':
    main()
