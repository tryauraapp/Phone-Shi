import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import s25_android17_platform as platform_profile


class S25PlatformTests(unittest.TestCase):
    def test_identity_retains_android17_abi_and_security_settings(self):
        original = ('ro.product.product.model=sdk_gphone64_x86_64\n'
                    'ro.build.version.release=17\nro.build.version.sdk=37\n'
                    'ro.product.cpu.abi=x86_64\nro.debuggable=0\n')
        result = platform_profile.patch_properties(original)
        for line in original.splitlines()[1:]:
            self.assertIn(line + '\n', result)
        self.assertIn('ro.product.model=SM-S931B\n', result)
        self.assertIn('ro.product.product.model=SM-S931B\n', result)
        self.assertIn('ro.build.fingerprint=samsung/pa1qxxx/pa1q:17/', result)
        self.assertNotIn('ro.hardware=', result)
        self.assertNotIn('ro.soc.', result)
        with self.assertRaises(ValueError):
            platform_profile.patch_properties('ro.product.model=a\nro.product.model=b\n')

    def test_private_image_persists_without_touching_userdata_or_sdk_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sdk = root / 'sdk'
            source = sdk / platform_profile.IMAGE_RELATIVE
            source.mkdir(parents=True)
            (source / 'system.img').write_bytes(b'stock system')
            (source / 'ramdisk.img').write_bytes(b'stock ramdisk')
            asset = root / 's25.img'
            asset.write_bytes(b'lab s25 image')
            avd = root / 'phone.avd'
            avd.mkdir()
            (avd / 'config.ini').write_text('AvdId=phone\nimage.sysdir.1=old\n')
            (avd / 'userdata-qemu.img').write_bytes(b'private user data')
            with patch.object(platform_profile, 'SOURCE_SHA256', hashlib.sha256(b'stock system').hexdigest()), \
                 patch.object(platform_profile, 'IMAGE_SHA256', hashlib.sha256(b'lab s25 image').hexdigest()):
                saved = platform_profile.install(avd, sdk, asset)
                self.assertEqual(saved, platform_profile.install(avd, sdk, asset))
                self.assertEqual(platform_profile.launch_options(avd), ['-sysdir', str(avd / 's25-platform')])
                self.assertEqual((avd / 'userdata-qemu.img').read_bytes(), b'private user data')
                self.assertEqual((source / 'system.img').read_bytes(), b'stock system')
                self.assertTrue((avd / 's25-platform/ramdisk.img').is_symlink())
                image = avd / 's25-platform/system.img'
                self.assertFalse(image.is_symlink())
                image.chmod(0o600)
                image.write_bytes(b'corrupted')
                with self.assertRaises(ValueError):
                    platform_profile.launch_options(avd)


if __name__ == '__main__':
    unittest.main()
