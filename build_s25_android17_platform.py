#!/usr/bin/env python3
"""Rebuild the pinned S25 Android 17 lab image without modifying the SDK."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from s25_android17_platform import IMAGE_RELATIVE, IMAGE_SHA256, SOURCE_SHA256, patch_properties, sha

# Valid only for the exact source hash above: GPT super partition + product extent.
PRODUCT_OFFSET = 2097152 + 2029568 * 512
PRODUCT_LENGTH = 3216424 * 512


def tree(root):
    result = {}
    for path in [root, *root.rglob('*')]:
        s = path.lstat()
        value = [stat.S_IFMT(s.st_mode), stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid]
        if path.is_symlink():
            value.append(os.readlink(path))
        elif path.is_file():
            value.append(sha(path))
        value.append({k: os.getxattr(path, k, follow_symlinks=False).hex()
                      for k in os.listxattr(path, follow_symlinks=False)})
        result[str(path.relative_to(root))] = value
    return result


def build(sdk, tools, output):
    if os.geteuid() != 0:
        raise ValueError('Root is required to preserve Android ownership and SELinux xattrs')
    sdk, tools, output = Path(sdk).resolve(), Path(tools).resolve(), Path(output).resolve()
    source = sdk / IMAGE_RELATIVE / 'system.img'
    if sha(source) != SOURCE_SHA256:
        raise ValueError('Unsupported SDK system image')
    version = subprocess.check_output([str(tools / 'fsck.erofs'), '--version'], text=True)
    if '1.8.10' not in version:
        raise ValueError('Use the tested official erofs-utils 1.8.10 build')
    output.mkdir(mode=0o700)
    original = output / 'product-stock.erofs'
    with source.open('rb') as src, original.open('xb') as dst:
        src.seek(PRODUCT_OFFSET)
        remaining = PRODUCT_LENGTH
        while remaining:
            block = src.read(min(8 * 1024 * 1024, remaining))
            if not block:
                raise ValueError('Source product extent is truncated')
            dst.write(block)
            remaining -= len(block)
    extracted = output / 'product-tree'
    subprocess.run([str(tools / 'fsck.erofs'), '--xattrs', '--preserve', '--extract=' + str(extracted), str(original)], check=True)
    props = extracted / 'etc/build.prop'
    before = tree(extracted)
    original_text = props.read_text()
    (output / 'product-build.prop.before').write_text(original_text)
    props.write_text(patch_properties(original_text))
    changed = tree(extracted)
    differences = [key for key in before if before[key] != changed[key]]
    if differences != ['etc/build.prop']:
        raise RuntimeError('Unexpected source tree changes: ' + repr(differences))
    product = output / 'product-s25.erofs'
    with (output / 'build.log').open('w') as log:
        subprocess.run([str(tools / 'mkfs.erofs'), '-zlz4hc,9', '-C65536', '-T1230768000',
                        '-U56320177-304d-562f-a30b-b1ebcc1bae0e', str(product), str(extracted)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    if product.stat().st_size > PRODUCT_LENGTH:
        raise ValueError('Rebuilt filesystem exceeds its unchanged logical extent')
    roundtrip = output / 'roundtrip'
    subprocess.run([str(tools / 'fsck.erofs'), '--xattrs', '--preserve', '--extract=' + str(roundtrip), str(product)], check=True)
    if tree(roundtrip) != changed:
        raise ValueError('Rebuilt content or Android metadata differs')
    image = output / 'system.img'
    subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(source), str(image)], check=True)
    with image.open('r+b') as dst, product.open('rb') as src:
        dst.seek(PRODUCT_OFFSET)
        shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
    digest = sha(image)
    if digest != IMAGE_SHA256:
        raise ValueError('Rebuilt image differs from the tested asset; review before use')
    image.chmod(0o444)
    (output / 'build-evidence.json').write_text(json.dumps(dict(source_sha256=SOURCE_SHA256,
        image_sha256=digest, filesystem_entries=len(changed), changed_files=differences,
        ownership_modes_xattrs_preserved=True, shared_sdk_modified=False), indent=2) + '\n')
    print('Pinned Android 17 S25 lab image rebuilt and verified: ' + str(image))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--tools', required=True, help='Directory containing erofs-utils 1.8.10 executables')
    parser.add_argument('--output', required=True, help='A new work/output directory; never overwritten')
    args = parser.parse_args()
    build(args.sdk, args.tools, args.output)
