#!/usr/bin/env python3
"""Install a tested read-only Android 17 S25 lab image into one closed AVD."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


PROFILE_ID = 's25-android17-v2'
IMAGE_SHA256 = '1dc01026cc5065aee0074cd40cb834b12256f3dd6e17315e7c1a99c3d48496da'
SOURCE_SHA256 = '11efb3b1510ec16445a41366d539541ac830c14ba3e7f7d44926370e3c02ec62'
IMAGE_RELATIVE = 'system-images/android-37.0/google_apis_playstore/x86_64'
IDENTITY = dict(brand='samsung', manufacturer='samsung', model='SM-S931B', name='pa1qxxx', device='pa1q')
FINGERPRINT = 'samsung/pa1qxxx/pa1q:17/CE2A.260420.051.A2/16418371:user/release-keys'


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def properties():
    result = {'ro.product.' + k: v for k, v in IDENTITY.items()}
    for part in ('product', 'system', 'system_ext', 'vendor', 'odm'):
        result.update({'ro.product.' + part + '.' + k: v for k, v in IDENTITY.items()})
    for part in ('product', 'system', 'system_ext', 'vendor', 'odm', 'bootimage', 'system_dlkm', 'vendor_dlkm'):
        result['ro.' + part + '.build.fingerprint'] = FINGERPRINT
    result.update({'ro.build.fingerprint': FINGERPRINT, 'ro.build.product': 'pa1q',
                   'ro.build.description': 'pa1qxxx-user 17 CE2A.260420.051.A2 16418371 release-keys',
                   'ro.build.characteristics': 'phone'})
    return result


def patch_properties(text):
    pending = properties()
    lines = []
    seen = set()
    for line in text.splitlines():
        key = line.split('=', 1)[0]
        if key in properties():
            if key in seen:
                raise ValueError('Duplicate identity property in source: ' + key)
            seen.add(key)
            line = key + '=' + pending.pop(key)
        lines.append(line)
    lines += ['', '# Android 17 S25 lab identity profile; stock APIs and hardware remain virtual.']
    lines += [k + '=' + v for k, v in pending.items()]
    return '\n'.join(lines) + '\n'


def install(avd_dir, sdk, asset):
    """Caller must stop the target AVD first; existing data are never replaced."""
    avd_dir, sdk, asset = Path(avd_dir).resolve(), Path(sdk).resolve(), Path(asset).resolve()
    manifest = avd_dir / 'android17-s25-platform.json'
    if not (avd_dir / 'config.ini').is_file():
        raise ValueError('AVD config is missing')
    source = sdk / IMAGE_RELATIVE
    if sha(source / 'system.img') != SOURCE_SHA256 or sha(asset) != IMAGE_SHA256:
        raise ValueError('Stock source or tested S25 image hash differs')
    private = avd_dir / 's25-platform'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved['profile'] != PROFILE_ID or saved['private_sysdir'] != str(private):
            raise ValueError('Existing platform manifest differs')
        launch_options(avd_dir)
        return saved
    if private.exists():
        raise ValueError('Unregistered private platform directory exists; refusing overwrite')
    temporary = Path(tempfile.mkdtemp(prefix='.s25-platform-', dir=avd_dir))
    try:
        for path in source.iterdir():
            if path.name == 'system.img':
                shutil.copyfile(asset, temporary / path.name)
                (temporary / path.name).chmod(0o444)
            else:
                (temporary / path.name).symlink_to(path)
        if sha(temporary / 'system.img') != IMAGE_SHA256:
            raise ValueError('Private platform copy hash differs')
        temporary.rename(private)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    config = avd_dir / 'config.ini'
    backup = avd_dir / 'config-before-s25-platform.ini'
    if not backup.exists():
        shutil.copy2(config, backup)
    lines = config.read_text().splitlines()
    lines = [line for line in lines if not line.startswith('image.sysdir.1=')]
    config.write_text('\n'.join(lines + ['image.sysdir.1=' + str(private) + '/']) + '\n')
    saved = dict(schema=1, profile=PROFILE_ID, private_sysdir=str(private), identity=IDENTITY,
                 fingerprint=FINGERPRINT, android='17', sdk=37, image_sha256=IMAGE_SHA256,
                 stock_system_sha256=SOURCE_SHA256, modified_file='/product/etc/build.prop',
                 root=False, hardware='ranchu', shared_sdk_modified=False)
    manifest.write_text(json.dumps(saved, indent=2) + '\n')
    manifest.chmod(0o600)
    return saved


def launch_options(avd_dir):
    path = Path(avd_dir) / 'android17-s25-platform.json'
    if not path.exists():
        return []
    saved = json.loads(path.read_text())
    private = Path(avd_dir).resolve() / 's25-platform'
    if saved.get('profile') != PROFILE_ID or saved.get('private_sysdir') != str(private):
        raise ValueError('S25 platform manifest does not match this AVD')
    if sha(private / 'system.img') != IMAGE_SHA256:
        raise ValueError('Private S25 image changed; refusing launch')
    return ['-sysdir', str(private)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avd-dir', required=True)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--asset', required=True)
    args = parser.parse_args()
    install(args.avd_dir, args.sdk, args.asset)
    print('Private Android 17 S25 platform installed; userdata and identifiers preserved.')
