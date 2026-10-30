# Older S25 setup on Android 17

The current VPS standard is `vps-android17-s25-v2`. It ports the older phone's
app-visible Samsung identity and compatible user settings to the newer Android
17 VM. It uses a private read-only platform image and does not install Magisk.

## Resulting identity and settings

| Field | Android 17 S25 profile |
| --- | --- |
| Manufacturer / brand | `samsung` |
| Model | `SM-S931B` |
| Product / device | `pa1qxxx` / `pa1q` |
| Friendly name | Galaxy S25 |
| Android / API | 17 / 37 |
| Build ID / incremental | `CE2A.260420.051.A2` / `16418371` |
| Security patch | 2026-08-05 |
| Serial / IMEI / Android ID | Existing per-device values preserved |
| Battery | Native 83%, unplugged, discharging, good health |
| Network | Mobile data on, Wi-Fi off, native home voice/data, validated cellular default |
| Display | 1080×2340, density 416, portrait locked |
| Brightness / timeout | 102 manual / 2147483647 ms |
| Time zone / location | GMT / location mode 3, no invented GPS coordinates |
| Guest security | SELinux Enforcing, non-debuggable, secure ADB, no `su` or Magisk |

The property profile also sets the partition identity fields, Android 17 lab
fingerprints, build product/description and phone characteristics. Its Samsung
fingerprint is a **lab fixture**, combining S25 product labels with the actual
Android 17 SDK build version. It is not an official Samsung firmware release.
The real x86_64 ABI, ranchu hardware, software renderer and Android kernel remain.
Qualcomm/Adreno hooks, root/mount overlays and unsupported battery telemetry from
the older setup are not installed on this rootless platform.

The live comparison with the old phone confirmed that compatible battery,
mobile-data, Wi-Fi, display, brightness, timeout and rotation settings already
matched. The missing app-visible identity has now been ported into the image.

## Files and default provisioning

- Profile source: `phone_setup_standard.json`.
- Per-AVD installer and launch validation: `s25_android17_platform.py`.
- Reproducible image builder: `build_s25_android17_platform.py`.
- VPS asset: `/opt/android-vm/platform-profiles/s25-android17-v2/system.img`.
- Asset SHA256: `1dc01026cc5065aee0074cd40cb834b12256f3dd6e17315e7c1a99c3d48496da`.
- Per-phone image: `/opt/android-vm/avd/NAME.avd/s25-platform/system.img`.
- Per-phone manifest: `android17-s25-platform.json` in that AVD directory.

`setup_vps_phone.py create` now installs this profile for every new VPS phone.
The saved identity launcher detects the platform manifest, verifies the private
image hash and launches with its private `-sysdir`. Each phone gets its own
read-only image copy, fresh userdata and independently reserved identifiers.

Native `-prop ro.product.*` options are rejected by Android 17's property policy.
The emulator also recorded a private `-system` path while actually opening the
shared SDK image. The working route uses both the private `image.sysdir.1` config
and `-sysdir`; `/proc/<pid>/fd` confirmed the private image is actually in use.
Do not reinstate the failed boot-property or `-system` attempts as defaults.

## Build provenance and verification

The shared SDK image is never edited. Its pinned SHA256 is
`11efb3b1510ec16445a41366d539541ac830c14ba3e7f7d44926370e3c02ec62`.
For this exact image the builder extracts the product logical extent, preserves
Android ownership/modes/SELinux xattrs, changes only `/product/etc/build.prop`,
rebuilds EROFS, and writes it into a copy of the same GPT/super image. Other
logical partitions and boot images are retained.

The tested tools are official erofs-utils **1.8.10**, source commit
`51b5939b5f783221310d25146e6a2019ba8129b6`, from
[kernel.org](https://git.kernel.org/pub/scm/linux/kernel/git/xiang/erofs-utils.git/).
The VPS tools are installed privately at
`/opt/android-vm/standard-setup/erofs-tools/bin/`. The older system tools were not
replaced; their extraction did not preserve the required xattrs by default.

Rebuild into a new work directory:

```sh
python3 /opt/android-vm/standard-setup/build_s25_android17_platform.py \
  --sdk /opt/android-vm/sdk \
  --tools /opt/android-vm/standard-setup/erofs-tools/bin \
  --output /opt/android-vm/standard-setup/rebuild-s25-new
```

Root is needed on the **host** to preserve filesystem metadata; the guest stays
unrooted. The builder refuses an unexpected source image, checks all 776
filesystem entries after rebuilding, and requires the exact tested output hash.
An independent complete rebuild produced the identical tested image.

The accepted-app migration candidate exported a fresh Duck report identifying
`samsung SM-S931B (Android 17, API 37)`, with **3 Danger / 3 Warning / 20 Ready**.
The unchanged APK hash still matches the saved build 1097. Bootloader, TEE and
Virtualization remain real VM limitations; the branding does not establish
hardware-backed Samsung identity or physical-device attestation.

Candidate report and property/filesystem evidence are stored beside the VPS
asset. Main-phone verification records are under
`/opt/android-vm/phones/Duck_Platform_API37/`.

## Rollback without losing phone data

Stop only the target phone's service. Rename `android17-s25-platform.json` to
`android17-s25-platform.json.disabled` so its launch helper stops selecting the
private image. Restore `config-before-s25-platform.ini` to `config.ini` and the
saved pre-v2 profile/certificate in the phone's record directory, then start its
service. Keep userdata, identifier registry, private engines and platform image.
The older phone and original Redroid backups remain separate and untouched.

Local verification uses `test_s25_android17_platform.py`,
`test_linux_avd_identity.py` and `test_setup_vps_phone.py` (13 focused tests).
The runtime waits for a stable native portrait lock after the emulator's
asynchronous boot display setup, restoring it if a late callback resets rotation.
