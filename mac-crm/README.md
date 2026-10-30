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
  (active / paused / retired). **Open** on a row (or in the side pane) streams
  that phone underneath the table with full touch and keyboard control; several
  phones can be open side by side, each with reconnect, open-in-browser and
  close buttons. Selecting a row opens a side pane with the record, live
  details, installed apps, **Screen** (an adb screenshot) and **Start / Stop**
  through the phone's systemd unit or docker container.
- **Creators**: name, Instagram, TikTok and OnlyFans handles, notes, the
  phones assigned to them, and their Snap accounts (with add and assign).
- **Snap Accounts**: Snapchat accounts with username, display name, email,
  phone number, status (warming / active / locked / banned) and notes. Each can
  be assigned to a creator and to the phone it lives on, from the table, the
  detail pane, or from inside the creator's page.
- **Apps**: every package seen on a phone with an editable friendly name and
  the phones it is installed on.
- **VDS Settings**: host, SSH user and key, adb path on the VDS, viewer base
  URL, auto-refresh interval, and a connection test.

## How the embedded phone works

Each open phone is a `WKWebView` loading the VDS's own browser phone page,
`<viewer base>/go?udid=<serial>`, which is the ws-scrcpy stream behind nginx
and a trusted Let's Encrypt certificate. A user script injected into that page
hides the device list, modal chrome and control column and scales the two
stream canvases (video and touch layer) to fill the frame, so the card shows
only the live phone screen. Mouse and keyboard in the web view go to the phone
exactly as they do in a browser. Back, Home, Recents and Power buttons in the
card header send adb key events over SSH. The web view is kept alive while the
phone stays open, so switching sections does not restart the stream.

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
