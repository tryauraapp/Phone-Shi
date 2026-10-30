# Standard phone setup

This is the saved default for **new VPS phones**, combining the working Android
17 platform with the compatible original phone settings and persistent unique
identifiers. Profile version: `vps-android17-s25-v2`, saved 30 October 2026.
Version 2 also carries the older phone's app-visible Samsung/S25 identity onto
Android 17 using a private read-only product image. See `S25_ANDROID17.md`.

The source of truth is `phone_setup_standard.json`. The executable workflow is
`setup_vps_phone.py`. Each phone receives a private snapshot of the profile so
later edits cannot silently change an existing phone. The original macOS
Android 15 installer is retained as a separate legacy workflow; it does not
implement this Linux x86_64 standard.

## Create every new VPS phone through this command

The standard bundle is saved on the VPS at `/opt/android-vm/standard-setup/`.
Use a new name and unused emulator/gRPC ports for each phone:

```sh
python3 /opt/android-vm/standard-setup/setup_vps_phone.py create \
  --name Phone_001 --port 5564 --grpc-port 8564 \
  --duck-apk /opt/android-vm-staging/duck-detector-original.apk
```

Run on the VPS as root with Python 3.11+ and the existing official SDK, KVM,
systemd and authorized controller key. The command validates the supported SDK
and image hashes, refuses existing names/services or occupied ports, and creates
fresh userdata. It installs boot/runtime services and verifies two cold boots.
It flushes guest storage before stopping the emulator and checks the actual
installed Duck APK hash after reboot, rather than trusting a cached package record.
It does not copy an existing phone's userdata or identifiers, and it does not
restart other phones. Failed new setups are stopped and disabled with their
files retained for recovery.

Preview all stages without creating a phone:

```sh
python3 /opt/android-vm/standard-setup/setup_vps_phone.py plan
```

## The complete 34-stage workflow

1. Check Linux x86_64, accessible KVM and at least 8 GiB free storage.
2. Validate the saved official Google Play API 37 system image and emulator
   binary hashes. The tested emulator is 37.2.13; guest Android is 17 with the
   2026-08-05 security patch. The installed image's own `source.properties`
   reports revision 7; hashes identify the exact saved build.
3. Reserve a new AVD name, private directory and separate unused control ports.
4. Create fresh userdata, preserving every other phone and its files.
5. Configure four vCPUs, 4096 MiB RAM and a 6 GiB data partition.
6. Reserve one random serial and one Luhn-valid synthetic IMEI in the shared
   uniqueness registry. Generate once, then preserve across boots.
7. Prepare validated private host engines and the tested S25 platform image.
   Shared SDK binaries/images remain unchanged; each phone boots a private copy
   whose product property file carries the S25 identity.
8. Set the saved Android serial through the emulator's native serial option.
9. Set the saved IMEI in the actual host modem responses and verify it through
   Android telephony. No Magisk or guest radio overlay is used.
10. Retain authenticated ADB and token-protected gRPC with local endpoints.
11. Install a separate persistent systemd boot service for this phone.
12. Boot the Google Play Android 17 base with the S25 lab identity and no guest root.
13. Record the freshly generated Android ID in the uniqueness registry and
    identity manifest; verify that later boots preserve it.
14. Verify Enforcing SELinux, `ro.debuggable=0`, `ro.secure=1`,
    `ro.adb.secure=1`, and absence of a guest `su` binary.
15. Set display resolution to 1080 × 2340.
16. Set display density to 416.
17. Lock portrait orientation with user rotation zero.
18. Set manual brightness to 102.
19. Set the screen timeout to 2147483647 milliseconds.
20. Set the friendly name to Galaxy S25. The private platform supplies
    `samsung / SM-S931B / pa1qxxx / pa1q` to Android APIs, with an Android 17
    lab fingerprint. The actual kernel, CPU architecture and renderer remain virtual.
21. Apply the saved GMT time zone and preserve automatic time/time-zone settings.
22. Retain location mode 3 without inventing GPS coordinates.
23. Enable mobile data and require an actually validated cellular default network.
24. Disable Wi-Fi and verify the saved setting.
25. Set native simulated voice/data registration to home, non-roaming service.
26. Set the native battery to 83%, present, good health, unplugged and discharging.
27. Reapply the saved settings and native battery/radio controls after each boot.
28. Install the unchanged, hash-checked Duck Detector APK, build 1097.
29. **Conditional:** install additional apps explicitly selected for this phone.
30. **Conditional:** configure a supplied per-phone proxy and matching GPS/time
    zone, with its own connectivity checks. No proxy was configured for the
    current VPS baseline. This extension needs a separate supported integration;
    the base create command does not accept proxy/GPS overrides.
31. **Conditional:** configure a supplied camera feed using the measured app
    preview and the documented camera workflow. No feed is configured by this
    baseline. The base create command does not alter camera calibration.
32. Cold-boot again and verify serial, IMEI, Android ID, security, saved settings,
    battery, cellular connectivity and installed Duck version.
33. Save the private profile snapshot, both verification reports and a completion
    record. Conditional stages not requested are recorded as such.
34. **Interactive:** open Duck, handle its agreement/arithmetic checkpoint when
    presented, and compare a fresh scan with the saved baseline. This is not
    silently marked complete by the automated installer.

The automated base record explicitly has `full_setup_complete=false` until the
interactive Duck review is completed and recorded. A successful base setup alone
does not claim an identical scan on every future image or that all red checks
have been resolved. Agreements and arithmetic verification may require the
user's action-time approval.

After reviewing and exporting **that phone's** fresh Duck report, record it with:

```sh
python3 /opt/android-vm/standard-setup/setup_vps_phone.py record-scan \
  --metadata /opt/android-vm/phones/Phone_001/phone.json \
  --report /absolute/path/to/that-phones-exported-report.txt
```

This rechecks the live phone and installed APK hash, requires the expected build
and all four baseline counts, saves the report/hash, and marks stage 34 reviewed.
An incomplete or changed scan fails rather than receiving a full completion mark.

## What is saved for each phone

Under `/opt/android-vm/phones/NAME/`:

- `phone.json`: AVD, SDK, service, port and registry paths.
- `setup-profile.json`: the full immutable-by-convention setup snapshot.
- `launch.sh`: the private-identity launch command and existing graphics flag.
- `verification-boot1.json` and `verification-boot2.json`: read-back evidence.
- `setup-complete.json`: automated/interactive/conditional completion status.

The AVD and its `linux-identifiers.json` are under
`/opt/android-vm/avd/NAME.avd/`. Identifier reservations are stored in
`/opt/android-vm/identities.sqlite3`; secure Android IDs are recorded as hashes.
Private records use owner-only file permissions. Each new phone has independent
userdata and identifiers; these are not regenerated on every reboot.

The current phone's adopted record is
`/opt/android-vm/phones/Duck_Platform_API37/`. Its already-working launcher is
retained. Its existing `android-legacy-profile.service` now runs the standard
runtime helper so **all** saved settings are restored after boot. Its previous
service definition is backed up as `runtime-service-before-standard.service`
in that phone's record directory. The settings were aligned and verified without
restarting the current phone. Portrait locking uses WindowManager after display
configuration, avoiding the rotation preference being reset during startup.
Its boot service also flushes guest storage before stopping; the former service
definition is saved as `phone-service-before-standard.service` beside the runtime
backup. Neither service change required restarting the working phone.

Managed new-phone services are `android-phone-PORT.service` and
`android-profile-PORT.service`. Recheck one phone with:

```sh
python3 /opt/android-vm/standard-setup/setup_vps_phone.py verify \
  --metadata /opt/android-vm/phones/Phone_001/phone.json
```

## Reconciliation with all original 34 step sites

The original working setup audited during this migration had 32 `step` calls,
plus two in its sourced `provision_file_profiles.sh`. Other Git revisions can
have different counts. Conditional calls and repeated boots also change the
runtime counter. This table records the migration mapping; the versioned JSON
above defines the current standard's exact 34 stages:

| Original step site | Current disposition |
| --- | --- |
| Pre-flight | Retained, with Linux/KVM/image/port checks |
| Creating AVD | Replaced with fresh rootless API 37 x86_64 AVD |
| First boot with private stock ramdisk | Official Android 17 base with private S25 property profile |
| Installing Device Red Flags | Duck Detector is the standard comparison app |
| Rooting private ramdisk with Magisk | Retired for this rootless platform |
| Booting rooted and completing Magisk setup | Retired |
| Granting Magisk superuser to adb shell | Retired; shell stays unprivileged |
| Baseline emulator-signal inventory | Retained as security/settings evidence and Duck comparison |
| Per-device Android radio IMEI overlay | Replaced with private host modem implementation |
| Cellular-only LTE network profile | Replaced with native validated cellular service; baseline reports NR |
| Late-boot QEMU property profile | Identity fields ported into the private Android 17 product image |
| Sensor-label overlay | Retired; actual virtual sensor labels retained |
| File aliases/vendor config overlay (sourced) | Retired; no guest mount overlays |
| Graphics label fixture (sourced) | Retired; actual software renderer retained |
| Applying Galaxy S25 profile | App-visible S25 identity, display and user settings ported to Android 17 |
| Post-change inventory | Retained in read-back verification |
| Starting modem signal simulation | Native modem registration retained; no invented fluctuating telemetry |
| Static proxy-derived GPS | Conditional on a supplied supported proxy configuration |
| Verifying battery, signal and GPS | Battery/network required; GPS only when configured |
| Per-device battery simulation | Replaced with native battery controls |
| Priming modem signal profile | Native home voice/data registration |
| Confirming proxy GPS before reboot | Conditional; never invent coordinates |
| Rebooting/verifying optimized base | Required two-boot verification |
| Installing apps | Duck required; other explicitly selected apps conditional |
| Installing Bumble from Google Play | Optional app-specific extension |
| Installing Plenty of Fish from Google Play | Optional app-specific extension |
| Installing Tinder from Google Play | Optional app-specific extension |
| Magisk mount isolation | Retired; guest has no Magisk or root |
| Removing Magisk manager while retaining daemon | Retired; neither is installed |
| Checking app-visible signals | Fresh unchanged Duck scan and actual API read-back |
| Certifying full setup for managed restarts | Rootless profile/evidence record with honest pending review |
| Bumble signup | Separate optional app workflow, not base phone setup |
| Plenty of Fish signup | Separate optional app workflow |
| Tinder guarded signup | Separate optional app workflow |

The old simulated 29°C/4100 mV battery readings, capacity/cycle fixtures,
Android 15 firmware fingerprint, Qualcomm/Adreno labels, root hooks and sysfs
mounts are not carried into the rootless image. Native battery readings are
retained for fields the control API cannot configure.
The replacement Samsung lab fingerprint retains the actual Android 17 build ID,
incremental version, API level and security patch; it is not an official Samsung
firmware release.

## Limits and recovery

The saved Duck baseline is **3 Danger / 3 Warning / 20 Ready / 0 Pending**.
The remaining reds are Bootloader, TEE and Virtualization. A VM has no genuine
Samsung firmware, hardware-backed TEE/StrongBox, physical SIM or mobile-carrier
public IP merely because its friendly name or synthetic identifiers differ.
The generic device ID API can return the IMEI; it is not a separate fourth
hardware identifier. Android app identifier permissions remain in force.

Preserve existing media, all existing userdata, and the graphics
`-feature -GLAsyncSwap` flag. Camera extensions must follow `VIDEO_CAMERA.md`
and the saved preview profile, with real preview-motion verification.

To stop a newly created phone, use `systemctl disable --now
android-phone-PORT.service`; its data, profile and identifiers remain available.
Do not delete a phone directory to retry a failed setup. Inspect its service
logs and saved files first. Resume a retained incomplete setup with
`setup_vps_phone.py resume --metadata /opt/android-vm/phones/NAME/phone.json
--duck-apk /opt/android-vm-staging/duck-detector-original.apk`. It preserves the
same Android ID, serial, IMEI and userdata, and refuses an already completed base
setup. Current-phone identifier rollback is documented in
`LINUX_AVD_IDENTITY.md`; original Redroid rollback is retained separately.

## Validation of the saved workflow

`Standard_Setup_Check_20261030` was created with fresh userdata on separate
emulator/control ports 5562/8562. Both final boot reports verify unique persisted
identifiers, the actual installed Duck APK hash, Enforcing SELinux, an unrooted
guest, saved settings, 83% discharging battery and validated cellular data.
Nine focused local tests also pass across setup and identity helpers.

The test phone is stopped and disabled, with its files preserved. Its Duck
startup/scan remains correctly marked pending; no agreement or verification
checkpoint was bypassed or silently recorded as accepted. The existing 5556
phone remains running and its full current profile was verified separately.
