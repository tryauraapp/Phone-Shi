# Phone Shi VPS V2

This folder is the Linux/VPS deployment edition. The original Mac state is
preserved separately in `Phone-Shi-MAC-V1`; this repository contains no copied
AVD disks, access tokens, proxy credentials, creator uploads, or control-panel
database from that snapshot.

## Supported host

- Ubuntu 22.04 or 24.04, x86-64
- a dedicated or nested-virtualization VM exposing `/dev/kvm`
- at least 4 vCPU and 4 GB RAM per concurrently running emulator, plus host
  overhead (the Android guest RAM setting alone is not the total host usage)
- SSD/NVMe storage; allow roughly 12–20 GB per phone after working data and
  backups

Run `python3 vps_preflight.py` first. A VPS without `/dev/kvm` is not suitable;
software emulation is too slow for this deployment.

## Install

Google changes the command-line-tools download filename over time. Copy the
current **Linux command line tools only** link from Android Studio's official
download page and run:

```bash
sudo ANDROID_CMDLINE_TOOLS_URL='https://dl.google.com/android/repository/commandlinetools-linux-....zip' \
  ./install_vps.sh
```

The installer creates a locked-down `phone-shi` service account, installs the
Android 15 Google Play x86-64 image, copies the application to
`/opt/phone-shi`, generates an access token, and starts the private control
panel, X display and noVNC viewer.

Keep both web services on loopback. From the Mac, connect with:

```bash
ssh -L 8790:127.0.0.1:8790 -L 6080:127.0.0.1:6080 USER@VPS
```

Then open:

- control panel: `http://127.0.0.1:8790`
- emulator viewer: `http://127.0.0.1:6080/vnc.html`

Service configuration lives at `/etc/phone-shi/phone-shi.env`. Secrets must be
put there, never committed. Persistent data lives under `/var/lib/phone-shi`.

## Important portability boundary

The control panel, SQLite data, media preparation, Android SDK paths, service
management and remote display are packaged for Linux. Existing Mac AVDs cannot
be copied to this x86-64 host: they use an ARM64 image and Mac-specific private
emulator binaries.

The complete Mac phone-provisioning path also contains binary transformations
that explicitly recognize a particular ARM64 Mach-O emulator build. Those are
not valid on the Linux ELF x86-64 emulator. V2 therefore leaves those modules
unchanged and will not claim that the full Mac device profile or its camera
renderer calibration has been reproduced on Linux. A new Linux AVD/profile
must be created and validated on the actual VPS before that host is used for
phone workloads.

Likewise, `camera_profiles/s25-native.json` is evidence for the saved Mac S25
renderer only. On a VPS, measure the real app preview, prepare to that size, and
prove changing Camera2 texture pixels with `camera_probe/build_and_run.py`.
Do not treat a first frame or elapsed playback time as proof.

## Operations

```bash
sudo systemctl status phone-shi-control phone-shi-display phone-shi-novnc
sudo journalctl -u phone-shi-control -f
sudo systemctl restart phone-shi-control
```

Back up `/var/lib/phone-shi` and `/etc/phone-shi/phone-shi.env` separately.
The install directory is replaceable application code; the state directory is
not.

## Create phones from the CRM

Open **Phones → New phone**. Choose the app, exact NodeMaven US state/city,
guest RAM/cores, and that phone's camera video. The first run also asks for a
NodeMaven API key; it is stored mode `0600` under the external control-panel
state directory and is never returned to the browser.

Provisioning is asynchronous and its stage, progress, and private log survive a
control-panel restart. The worker creates an Android 15 Google Play x86-64 AVD,
provisions and verifies its city-targeted T-Mobile proxy, saves the
proxy-derived timezone/GPS, prepares the native 3:4 camera source, cold-boots
through the proxy, checks Camera2 texture motion, and applies bounded battery
state.

Google Play authentication and installation remain visible user checkpoints.
When the phone row says **Action needed**, use **Screen**, complete Play sign-in
and install the selected app, then click **Verify setup**. Only an observed
installed package and passing camera/runtime checks produce the VPS setup
certificate that enables normal **Open** launches.

The VPS certificate records the real Google Android Emulator model and x86-64
ABI. It does not claim the standard Linux emulator is a physical Samsung
device; the Mac-only ARM64 identity transformations remain outside this
workflow.
