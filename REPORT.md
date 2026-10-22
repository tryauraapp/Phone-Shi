# Galaxy S25 AVD Lab — Historical Report

Historical observations from the original workstation and earlier fixture
versions follow. For current behavior and setup, use [README.md](README.md)
and [SETUP.md](SETUP.md). Generated reports and device backups referenced here
are local artifacts and are not shipped in this repository.

## QEMU and sensor-label follow-up — 2026-10-21, 21:16

Both requested checks now clear in the installed, unchanged diagnostic APK after a reboot:

| Check | App-visible result |
|---|---|
| `ro.kernel.qemu` | `0` |
| `ro.boot.qemu` | `0` |
| Virtual sensor names | No tested virtual name markers; 18 sensors still exposed |

The new `device_qemu_profile.sh` runs as `/data/adb/service.d/97-s25-qemu.sh` after `sys.boot_completed=1`. It preserves original values in `/data/adb/s25-avd-lab/qemu.original` and restores both if either override fails. Early init still reads the original emulator properties. Cached framework decisions and other QEMU properties are not changed. The emulator sensor, graphics and framework services were checked after the change and reboot.

The active HAL was `/vendor/lib64/hw/android.hardware.sensors@2.1-impl.ranchu.so`. `patch_sensor_labels.py` creates a Magisk overlay (`s25_sensor_labels`) replacing 17 `Goldfish ` label prefixes with equal-length `Samsung  ` labels and the vendor display string with a padded `Samsung Electronics`. It validates ELF64/AArch64, confines changes to non-executable `.rodata`, preserves the binary length, and saves before/after SHA-256 hashes. The actual driver's `.text` and `.plt` bytes were verified unchanged. The original vendor image is not modified. These are generic Samsung-branded lab labels, not an authenticated Galaxy S25 sensor inventory or behavior model. Framework-fused sensors retain their AOSP names/vendors.

After reboot, the sensor service still exposed 12 hardware sensors and the ordinary-app checker exposed 18 sensors, matching its pre-change count. Sensor events continued to arrive. The checker report is `device-checker/reports/after-qemu-sensors.json`: **3 red flags / 2 weak signals**, down from 5 / 2 before this change. Hardware identity, emulator files and graphics remain red flags; CPU and network context remain weak signals.

The setup script installs both changes before its existing profile reboot and verifies the read-back afterward. Options `--keep-qemu-flags` and `--keep-sensor-labels` skip them. The rollback action now restores the two properties, removes their boot service, and disables the sensor module for the following reboot. Seven automated tests pass, including partial-failure property restoration and executable-section preservation. The complete new-AVD provisioning flow has not been rerun.

Manual rollback on the current AVD:

```sh
adb -s emulator-5554 shell 'su -c "sh /data/adb/service.d/97-s25-qemu.sh --restore; touch /data/adb/s25-avd-lab/qemu.disabled; touch /data/adb/modules/s25_sensor_labels/disable"'
adb -s emulator-5554 reboot
```

The sensor labels originate in the HAL's metadata, consistent with the [AOSP Goldfish sensor implementation](https://android.googlesource.com/device/generic/goldfish/+/03460f6d67cc7a268a6af582f2f671fdf2e33379/sensors/sensors_qemu.c). No Play Integrity result or hardware attestation was requested or established.

## Current follow-up — 2026-10-21, Galaxy_S25_Lab

The running AVD is now `Galaxy_S25_Lab` on `emulator-5554`. The older sections below describe the earlier `Galaxy_s25_-_3` experiments and are retained as historical evidence.

Implemented and checked on the current AVD:

- Bumble's main and `:light` processes are on Magisk's enforced DenyList. A mount-namespace check confirmed `/system_ext/bin/su` was absent from both. Root remains installed for the boot services.
- The Magisk manager APK was backed up to `profiles/Galaxy_S25_Lab/backup/Magisk.apk`, then its package was uninstalled with data retained. Shell root and DenyList enforcement were verified afterward. Restore the UI with `adb -s emulator-5554 install -r profiles/Galaxy_S25_Lab/backup/Magisk.apk`.
- The identity profile now uses `samsung/pa1qxxx/pa1q:15/AP3A.240905.015.A2/S931BXXS4AYF1:user/release-keys`. Build.ID and Build.VERSION.INCREMENTAL match it after reboot. This is a **constructed Samsung-shaped fixture**, not an extracted, verified or attested Samsung firmware identity. Samsung documents [SM-S931B / S931BXXS4AYF1 / Android 15](https://doc.samsungmobile.com/SM-S931B/032402250224/ind.html); that release listing does not establish the exact full fingerprint used here.
- Per-device fixtures are generated with independent random seeds and saved as JSON. The current device starts at 77% / 27.3 °C. The battery boot service makes a bounded temperature random walk every five seconds and reduces charge by one point every eight minutes for this fixture. Other devices use eight to twelve minutes per point. Charge stops dropping at 5% for unattended lab sessions.
- The battery service survived a reboot. Temperature read-back changed from 27.3 to 27.4 and 27.1 °C in subsequent checks. This is framework telemetry simulation. Direct `BatteryManager` charge-counter reads still returned the emulator's `10000 µAh`, while `dumpsys battery get counter` returned the synthetic `2966810`. Health/wear percentage, voltage and cycle count are not changed.
- `emulator_signal_sim.py` varies modem signal in small steps every 15 seconds. The console supports RSSI and signal profiles; actual propagation can take another 15 seconds. On the running NR modem, `ssRsrp` changed from `-68` to `-102` following configuration. The controller runs on the Mac and stops on emulator disconnection; battery simulation runs inside Android at boot.
- `Device Red Flags` (`dev.emulab.devicecheck`) was built, installed and tested in an ordinary app sandbox, then added to the same enforced DenyList as Bumble. It requires no superuser or Internet permission. It is a public-heuristic checker, not Bumble's proprietary detector.

Saved checker results:

| State | Red flags | Weak signals |
|---|---:|---:|
| Before root isolation | 8 | 3 |
| With matching root isolation | 7 | 3 |
| After metadata update and manager removal | 5 | 2 |

The remaining red flags are ranchu hardware, QEMU properties, emulator files, virtual sensor names and the emulator graphics renderer. The remaining weak signals are emulator-style network addressing and the Apple CPU implementer under a claimed Samsung model. These have **not** been spoofed. Neither a passing Play Integrity verdict nor a locked physical-device bootloader has been established. Empty boot-state properties are reported as unknown.

Reports and screenshot are under `device-checker/reports/`. The APK is `device-checker/DeviceRedFlags.apk`; its sources and offline build instructions are in `device-checker/README.md`. The five lab tests pass, including fixture preservation, bounded temperature changes, slow charge movement, reset on battery-command failure, signal-step bounds, and coherent build fields. A full new-device setup was not run during this follow-up.

New setup options include `--fingerprint VALUE`, `--hide-root-package PKG`, `--no-battery-sim`, `--no-signal-sim`, `--no-root-isolation` and `--keep-magisk-app`. By default, setup isolates installed Bumble processes, removes the backed-up manager UI after configuration, and starts battery and radio simulations. Root persists. The identity and battery services depend on it.

Research: [Bumble privacy policy](https://bumble.com/privacy-policy/en-us) documents device-data collection but not a reproducible detection algorithm. [OWASP emulator detection](https://mas.owasp.org/MASTG-KNOW-0031/) and [root detection](https://mas.owasp.org/MASTG-KNOW-0027/) supply the checker's local heuristics. [Google's emulator console](https://developer.android.com/studio/run/emulator-console) documents the radio and power controls. Battery readings, individual app installation timestamps and storage fragmentation are not treated as reliable device-age proof.

Target: AVD `Galaxy_s25_-_3` (`emulator-5554`) · Android 15 / API 35 · arm64-v8a · Google Play image · Magisk 30.6 (rootAVD, FAKEBOOTIMG) · SELinux Enforcing.

Script: `galaxy_s25_avd_lab.sh` (actions: `apply`, `status`, `inventory`, `reboot`, `rollback`, `watch`).
Backups, logs, inventories: `~/galaxy_s25_avd_backups/Galaxy_s25_-_3/`.

## 1. Root cause of the `/data/adb` "Permission denied"

It was not caused by SELinux, Magisk, or file permissions. The cause was host-side shell quoting.

`adb shell` joins its arguments with spaces, and the guest's `/system/bin/sh` parses them again. So

```
adb shell su -c 'id; ls -ldZ /data/adb'
```

runs `su -c id` on the device and then `ls -ldZ /data/adb` **as uid 2000 (shell)**. The kernel log shows this directly:

```
avc: denied { getattr } comm="ls" path="/data/adb" scontext=u:r:shell:s0 tcontext=u:object_r:adb_data_file:s0
```

The old script's `su -c 'mkdir … && cp … && chmod …'` therefore ran `mkdir` as root and `cp` as shell. When the commands are quoted correctly (`adb shell "su -c '…'"`) or sent on stdin (`… | adb shell su`), root can read and write `/data/adb/service.d` normally. The new script sends every root command on stdin, so values containing spaces, `$` or quotes are also safe.

## 2. How the profile is applied

| Mechanism | What | When |
|---|---|---|
| `/data/adb/post-fs-data.d/99-s25-avd-lab.sh` | `magisk resetprop -n` for 62 props, from `/data/adb/s25-avd-lab/profile.props` | Before zygote, so `android.os.Build` in every app sees it |
| `/data/adb/service.d/99-s25-avd-lab.sh` | `wm size 1080x2340`, `wm density 416` | After `sys.boot_completed` (Android also persists these itself) |
| Host fallback (`--action watch`) | Re-applies from the Mac and soft-restarts the framework | Session only, labelled as such. Not needed here because service.d works |

Changes are in memory only and nothing on `/system` or `/vendor` is modified. Rollback deletes the two scripts and the lab directory, restores the original values with resetprop, resets `wm` and the peak refresh rate, then reboots.

**Verified:** apply → reboot → all 62 props correct. `post-fs-data` ran at 16:01:53, before `boot_progress_start` at 16:01:54. Also verified: rollback → reboot back to stock, and re-apply → full cold emulator restart → profile still active. Root (uid 0) and the Play Store, Play services and Services Framework (`com.android.vending`, `com.google.android.gms`, `com.google.android.gsf`) were confirmed after every step. The Play Store launches to its Sign-in screen; a Google account sign-in was **not** tested.

**One-time cost:** changing `ro.build.fingerprint` makes PackageManager treat the next boot as an OTA upgrade (`packages.xml` stores the build fingerprint). That boot is slow and can show "System UI isn't responding". This happened once; the following boot had 0 ANRs. Rollback triggers the same one-time effect.

## 3. Property classification

**Safe identity, changed** (`Build.MODEL/BRAND/MANUFACTURER/DEVICE/PRODUCT/FINGERPRINT/DISPLAY`):
- `ro.product{,.product,.system,.system_ext,.vendor,.odm,.bootimage,.system_dlkm,.vendor_dlkm}.{model,brand,manufacturer,device,name}` → `SM-S931B / samsung / samsung / pa1q / pa1qxxx`
- `ro{,.product,.system,.system_ext,.vendor,.odm,.bootimage,.system_dlkm,.vendor_dlkm}.build.fingerprint` → `samsung/pa1qxxx/pa1q:15/TEST.S25/123456:user/release-keys` (**synthetic**, not a real Samsung build)
- `ro.build.description`, `ro.build.display.id`, `ro.build.flavor`, `ro.build.product`, `ro.build.characteristics` (`emulator` → `phone`)

**Conditionally testable, changed** (only `Build.BOARD` / `Build.SOC_*` read these; HALs pick modules via `ro.hardware.*`):
- `ro.product.board` → `sun`. Snapdragon 8 Elite board codename; single source (Geekbench entry for SM-S931B).
- `ro.soc.manufacturer` → `QTI`, `ro.soc.model` → `SM8750`

**Unsafe or deliberately left alone:**

| Property | Value | Why it's kept |
|---|---|---|
| `ro.hardware`, `ro.boot.hardware` | `ranchu` | libhardware falls back to it for module lookup (e.g. `audio.primary.ranchu`). init imports `init.ranchu.rc` |
| `ro.hardware.{gralloc,power,vulkan,egl}`, `ro.boot.hardware.vulkan` | `ranchu`/`emulation` | Graphics and power HAL selection |
| `ro.kernel.qemu`, `ro.boot.qemu`, `ro.boot.qemu.*` | `1`, … | Read by emulator init services, framework (`Build.IS_EMULATOR`), sensors, telephony, adb setup |
| `ro.product.cpu.abi*` | `arm64-v8a` | Must match the real CPU or native libraries fail to load |
| `ro.build.version.*`, `ro.build.id` | 15 / 35 / `AE3A.240806.036` | Changing the OS version breaks compatibility checks and updates |
| `ro.boot.serialno`, `ro.serialno` | `EMULATOR37X2X12X0` | Not readable by normal apps (`serialno_prop`), and `Build.getSerial()` needs a privileged permission. Changing it gains nothing |
| `vendor.qemu.*`, `init.svc.*` emulator services | — | Emulator infrastructure: modem, Bluetooth, camera and time-zone pipes |
| `ro.build.host`, `ro.build.user` | `r-…-7jwq`, `android-build` | Left as-is. Easy to add later if wanted |

## 4. What apps can see (from the live SELinux policy)

The policy was checked for `untrusted_app` read rules:

- **Readable by any app:** `build_prop`, `fingerprint_prop`, `bootloader_prop` (all `ro.boot.*`, including `ro.boot.qemu*`, `ro.boot.verifiedbootstate`), `exported_default_prop` (`ro.kernel.qemu`), `soc_prop`, `build_vendor_prop`, `radio_prop` (`gsm.*`). On this emulator image apps can also read `vendor_qemu_prop` (`allow domain`) and `init_service_status_private_prop` (`allow coredomain`, so `init.svc.qemu-props` etc.).
- **Not readable:** `serialno_prop`, `qemu_sf_lcd_density_prop`, `userdebug_or_eng_prop`.

`android.os.Build` was checked with `probe/BuildProbe.dex` running under `app_process`. Because the props are set before zygote, app processes see the same values:

```
MODEL=SM-S931B  MANUFACTURER=samsung  BRAND=samsung  DEVICE=pa1q  PRODUCT=pa1qxxx
BOARD=sun  SOC_MANUFACTURER=QTI  SOC_MODEL=SM8750  DISPLAY=TEST.S25
FINGERPRINT=samsung/pa1qxxx/pa1q:15/TEST.S25/123456:user/release-keys
HARDWARE=ranchu  ID=AE3A.240806.036  HOST=r-493e2f23732658be-7jwq  SUPPORTED_ABIS=arm64-v8a
```

## 5. Signals that remain after spoofing (inventory diff)

There were 24 changes and 104 signals unchanged. Full lists are in `inventory/inventory-*.txt.cmp`.

- **Build API:** `Build.HARDWARE=ranchu`, `Build.HOST`, `Build.ID` (Google build id that contradicts the Samsung fingerprint), `Build.BOOTLOADER=unknown`.
- **Properties:** `ro.kernel.qemu=1`, `ro.boot.qemu=1` plus about 15 `ro.boot.qemu.*` (including the AVD name), `ro.hardware*=ranchu`, `vendor.qemu.*`, `init.svc.qemu-props` / `ranchu-*` / `goldfish-*`.
- **Files:** `/dev/goldfish_address_space`, `/dev/goldfish_sync`, `/vendor/etc/init/hw/init.ranchu.rc`, `/vendor/etc/fstab.ranchu`, `/vendor/lib64/hw/*ranchu*`.
- **Hardware model:** kernel `6.6.30-android15-…`; `/proc/cpuinfo` implementer `0x61` (Apple, i.e. the host M-series CPU) with 4 cores. A real S25 has 8 Oryon cores (implementer `0x51`). There are 19 sensors named "Goldfish …" from vendor AOSP.
- **GPU:** `GLES: Google … Android Emulator OpenGL ES Translator (ANGLE … SwiftShader)`.
- **Network / telephony:** SSID `AndroidWifi`, `10.0.2.16/24`, `gsm.version.ril-impl=android reference-ril 1.0`, baseband `1.0.0.0`, emulator operator `T-Mobile 310260`.
- **Display:** physical panel 1080×2400 (the override is logical), panel `EMU_display_0` by `GGL`. Refresh is 60 Hz by default. With `--vsync 120` the guest gets a fixed 120 Hz mode, not the S25's adaptive 1–120 Hz.
- **Battery:** fixed level 100, 25.0 °C.
- **Root:** `/system_ext/bin/su`, `/debug_ramdisk`, Magisk app installed, `ro.boot.verifiedbootstate=orange` (unlocked).

**Not fixable through properties at all:** CPU/cpuinfo, kernel, GPU renderer strings, sensor names and their behaviour, `/dev` nodes, network topology, battery behaviour, and timing or performance characteristics.

**Depends on remote attestation, not local identity:** Play Integrity returns a Google-issued signed and encrypted token. Android Key Attestation is a separate mechanism that provides an attestation certificate chain; supported physical devices can back this with secure hardware. Changing local properties does not generate either a valid hardware attestation chain or a passing Play Integrity token. No live Play Integrity verdict was collected for this report, so the actual verdict remains unverified. Changing the fingerprint may also affect Play certification.

### Live follow-up — 2026-10-21

Read-only inspection of the currently connected `emulator-5554` confirmed:

| Signal | Observed value |
|---|---|
| Model | `SM-S931B` |
| Fingerprint | `samsung/pa1qxxx/pa1q:15/TEST.S25/123456:user/release-keys` |
| Hardware | `ranchu` |
| `ro.kernel.qemu` / `ro.boot.qemu` | `1` / `1` |
| Build type / tags | `user` / `release-keys` |
| Build host / user | `r-493e2f23732658be-7jwq` / `android-build` |
| Bootloader | `unknown` |
| `ro.boot.verifiedbootstate` / `ro.boot.flash.locked` | Both empty in this inspection; the earlier `orange` observation is not confirmed for this session |
| Boot completed | `1` |
| Root executable | `/system_ext/bin/su` |
| Third-party packages listed by PackageManager | `com.bumble.app`, `com.topjohnwu.magisk` |
| Google Play Store / Play services | Both installed |

The Samsung identity override is active, but the device retains direct emulator and root indicators. The school checker APK is not present in the workspace or the third-party package listing. Its use of local checks versus server-verified Play Integrity is unknown. No additional device changes or successful bypass are claimed by this inspection.

References: [Play Integrity verdicts](https://developer.android.com/google/play/integrity/verdicts), [test responses for an app you control](https://developer.android.com/google/play/integrity/additional-tools).

## 6. Shared resource note

rootAVD patched the **shared** system image `system-images/android-35/google_apis_playstore/arm64-v8a/ramdisk.img` (the original is saved as `ramdisk.img.backup`). Any AVD built on that image boots with Magisk.

- `Galaxy_S25_2` uses a different image (`google_apis/arm64-v8a`), so it is not affected. It was never started or modified.
- An orphaned `~/.android/avd/Galaxy_s25.avd` folder (no `.ini`, so not listed by `emulator -list-avds`) does use the patched image.

This script does not touch any SDK image.
