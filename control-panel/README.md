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

## Boundaries

The panel prepares records and media. It does not automatically accept terms,
enter SMS codes, solve CAPTCHA, or perform selfie/identity verification. The
existing guarded signup helpers retain those manual stops. **Inspect current
screen** is read-only: it dumps the visible Android accessibility tree and
returns selectable labels without tapping the device.
