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
  that phone underneath the table in a phone-shaped frame with a side toolbar
  (Back, Home, Recents, volume, power, screenshot, reconnect, open in browser),
  with full touch and keyboard control. Several phones can be open side by
  side, and each can be popped out into its own window. Selecting a row opens a side pane with the record, live
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

Emulators created by the standard setup stream **natively**: the app runs
`Helper/phone_bridge.py` (from the repo's `.local/grpc-viewer-venv`, built on
`vds_phone_view/`) as a child process. The bridge finds the emulator's
token-protected gRPC endpoint on the VDS, forwards it through SSH, negotiates
WebRTC (VP8 over UDP) with the emulator's own stream, and writes raw RGB frames
to a pipe that a native `NSView` draws. Mouse and keyboard go back as gRPC
`sendTouch` / `sendKey` calls, injected as kernel input. If the phone's gRPC
allowlist does not include the WebRTC service, the bridge falls back to the
emulator's PNG screenshot stream and the card offers **Enable WebRTC**, which
installs `vds_phone_view/emulator_access.json` (stock plus the Rtc services)
into that phone's private emulator and restarts it. The globe button switches a
card to the browser stream; Redroid containers always use it.

### Browser stream

Each open phone is a `WKWebView` loading the VDS's own browser phone page,
`<viewer base>/go?udid=<serial>`, which is the ws-scrcpy stream behind nginx
and a trusted Let's Encrypt certificate. A user script injected into that page
hides the device list, modal chrome and control column, removes ws-scrcpy's
viewport-relative size clamps on the stream canvases, and scales the two
canvases (video and touch layer) to fill the frame. The page reports the real
video size back to the app, which sizes the frame to the phone's exact aspect
ratio, so the card shows only the live phone screen with no letterboxing. Mouse and keyboard in the web view go to the phone
exactly as they do in a browser. The toolbar's Back, Home, Recents, volume and
Power buttons send adb key events over SSH.

**Pasting from the Mac**: the Paste button (or ⌘V while the phone has focus)
reads the Mac clipboard, hands the text to ws-scrcpy's "push host clipboard to
device" action inside the stream page (substituting the browser clipboard read,
which WebKit would block), then presses Android's Paste key so the text lands
in the focused field. The web view is kept alive while the
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

## Creating phones

**New phone** (Phones toolbar) runs the standard VDS setup,
`/opt/android-vm/standard-setup/setup_vps_phone.py create`, as root over SSH
inside a tracked `systemd-run` unit named `phone-setup-<name>`, logging to
`/opt/android-vm/setup-logs/<name>.log`. The sheet suggests the next free
emulator/gRPC port pair and a name, lists the 34 stages from the script's
`plan`, and the phone appears as **Setting up** with its log, stage count and
Resume / Verify actions in the side pane while the two verification boots run.
Stage 34 (the Duck review) stays interactive and is recorded on the VDS with
`record-scan`. The Snap **New account** sheet can create a phone for the
account in the same way and links it automatically.
