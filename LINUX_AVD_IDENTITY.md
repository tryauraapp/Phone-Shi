# VPS Android 17 serial and synthetic IMEI

`linux_avd_identity.py` provisions persistent identifiers for the Linux x86_64
Google Play API 37 emulator. It is separate from the original macOS ARM64 S25
installer and its Android 15 Magisk radio patch. Do not apply that older patch
to this phone.

## Files on the VPS

- Launcher: `/opt/android-vm/start-platform.sh`
- Helper: `/opt/android-vm/legacy-compatible-profile/linux_avd_identity.py`
- Unique reservation registry: `/opt/android-vm/identities.sqlite3` (mode 0600)
- Current phone manifest:
  `/opt/android-vm/avd/Duck_Platform_API37.avd/linux-identifiers.json` (mode 0600)
- Current phone private host binaries:
  `/opt/android-vm/avd/Duck_Platform_API37.avd/private-emulator/`
- Read-back evidence: `/opt/android-vm/identity-validation-boot1.json` and
  `/opt/android-vm/identity-validation-boot2.json`
- Original launcher backup:
  `/opt/android-vm/identity-backup/start-platform-before.sh`

The manifest contains the actual reserved serial and IMEI. Each AVD name gets
one registry reservation, protected by unique constraints and a write transaction.
Running prepare again preserves that identity. A newly provisioned phone needs
its own AVD name, userdata, manifest and private engines; copying an existing
phone directory also copies its identifiers and Android ID.

The serial is a synthetic `LAB…` value passed through `-android-serialno`.
The synthetic IMEI starts with the lab prefix `0044`, has 15 digits and a valid
Luhn check digit. It is not a carrier-issued identity or evidence of a physical
Samsung handset. Android's usual app permissions still restrict identifier access.
The ADB transport remains `emulator-5556`; that transport label is independent
of Android's device serial.

## Provisioning and launch

Copy this helper and `device_identifiers.py` into the same directory. For an
existing phone, capture its Android ID while it is running:

```sh
python3 /opt/android-vm/legacy-compatible-profile/linux_avd_identity.py prepare \
  --sdk /opt/android-vm/sdk \
  --avd-dir /opt/android-vm/avd/Duck_Platform_API37.avd \
  --avd Duck_Platform_API37 \
  --registry /opt/android-vm/identities.sqlite3 \
  --baseline-serial emulator-5556 \
  --adb /opt/android-vm/sdk/platform-tools/adb
```

The existing launcher sets the SDK, AVD, HOME and runtime environment. Its final
command uses the helper's `launch` subcommand with those same four paths, followed
by `--` and the existing port, gRPC, graphics and snapshot arguments. Launch
validates the original SDK and private engine hashes before executing the private
launcher. Keep `-feature -GLAsyncSwap` and the existing native profile service.
The helper rejects incompatible SDK changes rather than silently repatching.

After Android finishes booting:

```sh
python3 /opt/android-vm/legacy-compatible-profile/linux_avd_identity.py verify \
  --serial emulator-5556 \
  --manifest /opt/android-vm/avd/Duck_Platform_API37.avd/linux-identifiers.json \
  --output /opt/android-vm/identity-validation.json \
  --adb /opt/android-vm/sdk/platform-tools/adb
```

Verification reads `ro.serialno`, `ro.boot.serialno`, and the Android telephony
service's device ID. It checks the preserved secure Android ID hash, Enforcing
SELinux and `ro.debuggable=0`. No guest root or Magisk is required.

## Emulator 37.2.13 implementation details

Only the two private x86_64 QEMU engines are modified; the launcher is an unchanged
physical copy. Resources link to the shared SDK. Starting the shared SDK launcher
can select the shared engine even with `-qemu-top-dir`, so execute the private
launcher and verify `/proc/<pid>/exe`.

The SDK serial validator's `^[a-zA-Z0-9._-,]+$` expression has a reversed range
which makes libc++ abort. The private engine moves the hyphen to the end of the
character class, preserving the intended character set and binary length.

Android 17's ranchu RadioModem reads `AT+CGSN=2`. The host's Cuttlefish
`MiscService::HandleGetIMEI` embeds its default in two overlapping eight-byte
`movabs` immediates as well as a string constant. Both forms must change. The
helper requires the exact known x86_64 instruction pattern and both known modem
constants exactly once; it replaces only their identifier bytes. Unsupported
builds fail before reserving or writing an identity.

Reference source:
[ranchu RadioModem](https://android.googlesource.com/device/generic/goldfish/+/refs/heads/main/hals/radio/RadioModem.cpp),
[host modem service](https://android.googlesource.com/device/google/cuttlefish/+/refs/heads/main/host/commands/modem_simulator/misc_service.cpp).

These changes do not add hardware-backed attestation, lock a VM bootloader,
provide a real SIM/mobile IP, or resolve Duck Detector's VM limitations. The
Shared SDK system/vendor images remain unchanged. The later S25 platform profile
boots a private product-image copy with changed identity properties; see
`S25_ANDROID17.md` for that separate profile and its rollback.

## Rollback

Restore `identity-backup/start-platform-before.sh` to `start-platform.sh`, then
restart only `android-phone-5556.service`. Keep its userdata, manifest, registry
and private files for recovery. This restores the former default serial/IMEI
without discarding app data. The separate original Redroid rollback remains in
`/opt/android-vm-staging/rollback-platform.sh`.

Local checks: `python3 -m unittest discover -s tests -p test_linux_avd_identity.py -v`.

## Verified on 2026-10-30

The copied candidate and two subsequent main-phone boots passed the Android
serial, boot serial, telephony IMEI, unchanged secure Android ID, Enforcing
SELinux and non-debuggable checks. The running main process was confirmed to
execute the private engine, and original SDK engine hashes still matched.
Battery returned to 83% discharging and validated default cellular connectivity
returned with Wi-Fi off. The fresh Duck Detector scan at 10:28:41 reported
3 Danger, 3 Warning, 20 Ready and 0 Pending, matching the prior baseline.

The candidate is stopped and its separate userdata retained at
`/opt/android-vm/avd/Identity_Test_API37.avd`. It is a migration-test copy with
the same identity, not a separately provisioned phone; do not run it alongside
the main phone for ordinary use. The original stopped Redroid data is retained.
