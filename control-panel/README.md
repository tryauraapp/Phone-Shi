# Creator Control

A small local/VPS web panel for preparing creator records, onboarding choices,
and account-specific photo files. It uses the existing `IGeelark` image variant
implementation directly; uploaded originals and the SQLite database stay under
the ignored `control-panel/data/` directory.

Photo location is not entered independently. The selected AVD must have its
saved `setup/proxy-location.json`; the panel uses that proxy-derived GPS center
and timezone for EXIF and refuses preparation when the record is unavailable.

## Run locally

```sh
python3 control-panel/server.py
```

Open <http://127.0.0.1:8790>. The default media source is
`../IGeelark/instagram_tool/variants.py`; override it with `IG_VARIANTS_PATH`.

The **Phones** section inventories the current host's saved AVDs and shows their
setup certificate, city-bound proxy policy, saved location/timezone, runtime
records and native camera profile. **Open with checks** starts only certified
phones through `emulator_proxy.py`; the existing fail-closed launcher restores
and verifies runtime state and camera motion before the panel reports Ready.
Phones launched directly from Android Studio are labelled Running outside CRM.
The Stop action targets only the selected AVD.

Each compact phone row shows its model, assigned app, proxy location and current
camera source. Dropping an MP4, MOV, M4V or WebM onto that phone validates the
upload, stores it privately, and calls `swap_camera_video.py`. The complete
saved S25 camera profile performs proportional 3:4 crop-to-fill preparation at
30 fps. A running phone is cold-restarted and must pass the normal Camera2
texture-motion check before it returns to Ready; other phones are untouched.

## Mac app

`Creator Control.app` is installed in the user's Applications folder. Opening
it starts the panel quietly when necessary and opens the local URL. To install
it again on a different Mac, update the absolute project path in
`Creator Control.applescript`, then run `install_mac_app.sh`.

## Run on a VPS

Set a strong token whenever the server is reachable beyond localhost:

```sh
export CONTROL_PANEL_TOKEN='replace-with-a-long-random-value'
python3 control-panel/server.py --host 0.0.0.0 --port 8787
```

Put HTTPS in front of it (for example, Caddy or an authenticated private
network). The browser asks for the token and holds it only in session storage.
Back up `control-panel/data/`; it contains private photos and account plans.
Each running panel controls phones on its own host. A Google Cloud installation
therefore shows the VPS fleet, while the Mac installation shows the Mac fleet;
remote host aggregation is a later deployment layer, not an implicit SSH call.

## Browser phone links

On a running phone, **Link / QR** opens an expiring link scoped to that saved
AVD. The viewer wakes it on connection and renews a 45-second keep-awake lease
every 15 seconds while the page is visible. After the last viewer disconnects
or goes into the background, the original screen timeout is restored. **Wake**
also wakes a phone manually switched off with its power button.

The primary display path is scrcpy H.264, remuxed by PyAV into fragmented MP4
without transcoding. MediaSource/ManagedMediaSource plays it in the browser.
One encoder per emulator serves multiple viewers; slow viewers reconnect to
the latest keyframe instead of accumulating delay. Streams stop after 15
seconds without viewers. Unsupported browsers retain the PNG fallback.

For an existing Linux installation, run `sudo bash install_browser_streaming.sh`
and use the updated `phone-shi-control.service`. The full VPS installer includes
this step. On Mac, install `scrcpy`, create `.local/controller-venv` with
`--system-site-packages`, and install `av>=19,<20` into it. The Mac controller
launcher automatically uses this environment when present. The streaming
server uses its own Android shell process and never modifies camera media.

## Boundaries

The panel prepares records and media. It does not automatically accept terms,
enter SMS codes, solve CAPTCHA, or perform selfie/identity verification. The
existing guarded signup helpers retain those manual stops. **Inspect current
screen** is read-only: it dumps the visible Android accessibility tree and
returns selectable labels without tapping the device.
