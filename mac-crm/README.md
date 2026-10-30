# Phone Shi CRM (native Mac app)

A SwiftUI app for the Mac that tracks the phones running on the Contabo VDS,
the creators they are run for, and the apps installed on each phone. It reads
live phone inventory over SSH and keeps creator records and phone assignments
on the Mac.

## What it shows

- **Dashboard**: totals plus tables of phones per model, per app, per creator,
  per state, per backend (Android emulator or Redroid container) and per
  Android version.
- **Phones**: one row per phone with status, model, creator assignment, installed
  third-party apps, the app currently on screen and a use flag
  (active / paused / retired). Selecting a row opens a side pane with the
  record, live details, installed apps, **Open viewer** (the VDS browser phone
  at `<viewer base>/go?udid=<serial>`), **Screen** (an adb screenshot) and
  **Start / Stop** through the phone's systemd unit or docker container.
- **Creators**: name, Instagram, TikTok and OnlyFans handles, notes, and the
  phones assigned to them.
- **Apps**: every package seen on a phone with an editable friendly name and
  the phones it is installed on.
- **VDS Settings**: host, SSH user and key, adb path on the VDS, viewer base
  URL, auto-refresh interval, and a connection test.

## How it reads the VDS

`Scripts/vds_inventory.py` is piped to `python3 -` on the VDS over the system
`ssh`. It lists adb devices, their build properties, the foreground app and
third-party packages, and matches each phone to its `android-phone-*.service`
unit or Redroid container. It is read-only. The build script embeds it into the
app, so the file in `Scripts/` is the one to edit.

Data lives in `~/Library/Application Support/Phone Shi CRM/crm.json`.

## Build and install

Needs only the command line Swift toolchain (no Xcode):

```sh
./build_app.sh --install
```

That builds `build/Phone Shi CRM.app` and copies it to `~/Applications`.

## Not included yet

Phone provisioning and warm-up are deliberately not wired in. The app manages
and observes phones; creating or warming a phone stays with the scripts in the
repository root until the chosen process is decided.
