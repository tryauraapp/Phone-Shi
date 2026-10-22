# Phone-Shi

Create and manage an Android Emulator lab phone with a Galaxy S25 identity
profile, a private Magisk-patched ramdisk, local diagnostics, optional app
installation, and a host-side authenticated HTTP proxy. The project also
includes an interactive Bumble onboarding helper.

The guest remains an Android 15 / API 35 Google Play ARM64 emulator. The
Samsung labels and simulated telemetry are lab fixtures; they do not provide
Samsung firmware, hardware attestation, a locked bootloader, a Play Integrity
pass, or guaranteed app acceptance.

## Host requirements

The supported workflow is macOS on Apple Silicon. Scripts target macOS Bash
3.2 and use Python 3.9+ with its standard library; there are no pip dependencies.
Install Android Studio / the Android SDK, Xcode Command Line Tools (`clang`,
Swift), a JDK (17+ recommended), and Git. `lz4` is optional for ramdisk checks;
`ffmpeg` is only needed if you extract camera frames.

SDK components used by the scripts:

- Android Emulator and platform-tools (`adb`).
- `system-images;android-35;google_apis_playstore;arm64-v8a`.
- Build tools `36.0.0`.
- An Android platform `android.jar` for building the checker. Its build script
  defaults to `$SDK/platforms/android-37.0/android.jar`; set `ANDROID_JAR` to
  your installed platform jar if needed.

SDK lookup order is `ANDROID_SDK_ROOT`, `ANDROID_HOME`, then
`$HOME/Library/Android/sdk`. Export the tools before following the examples:

```sh
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
```

Install the required image and tools through Android Studio's SDK Manager or
its `sdkmanager` CLI:

```sh
sdkmanager 'platform-tools' 'emulator' 'build-tools;36.0.0' \
  'system-images;android-35;google_apis_playstore;arm64-v8a'
```

Keep at least 8 GB free per new phone. The default allocation is 4096 MB RAM
and four CPU cores. Setup looks for rootAVD at `$HOME/Downloads/rootAVD` and
offers to clone `https://github.com/galihlasahido/rootAVD.git` when absent.
Override its location with `ROOTAVD_DIR` and its source with `ROOTAVD_REPO`.
This external dependency and any downloads it performs need network access.

## Fresh clone: prepare local inputs

```sh
git clone https://github.com/tryauraapp/Phone-Shi.git
cd Phone-Shi
bash device-checker/build.sh
```

The checker APK is built locally with a locally generated signing key. App
packages, personal media, credentials, device backups and captured account
screens are intentionally excluded from Git. Existing local copies remain on
the original workstation. Supply the following where needed:

| Local input | How it is used |
| --- | --- |
| `.local/emulator-proxy` | Default host proxy; absent means direct networking. |
| APK/XAPK files beside the setup script | Automatically installed; alternatively pass `--app PATH` repeatedly. |
| `bumble-signup/photos/` | At least four JPG/JPEG/PNG/WebP/HEIC photos for the signup helper. Four distinct files are sampled. |
| `bumble-signup/camera/phone-video.mp4` | Optional host recording; automatically selected as the front camera when present. |

Use an authorized app package and profile inputs. Review
`bumble-signup/profile-defaults.json` before signup: it currently selects United
States, birthday `2007-01-28`, visible gender, skipped recovery email, intention
“Open to seeing where things go,” and a manual photo-verification endpoint.
Name, gender, phone number and SMS code are supplied separately. The helper
requires an adult birthday.

## Configure the host proxy

Create `.local/emulator-proxy` locally with permissions `600`. Put a single
line in either supported format:

```text
host:port:username:password
http://username:password@host:port
```

Use URL-encoded credentials in the URL form for special characters. Keep this
file private; `.local/` is ignored by Git. No real endpoint or password is
shipped in this repository.

Creation reads this file automatically on every emulator launch/restart. An
asyncio relay binds an ephemeral loopback port on the Mac, authenticates to the
upstream proxy, and normalizes successful HTTP/1.0 CONNECT responses to HTTP/1.1
for netsim compatibility. Only the loopback URL is passed to the emulator.
The relay stops when its emulator exits. It does not install an Android VPN,
proxy setting, or certificate, and does not decrypt HTTPS.

This covers TCP only. UDP, QUIC, and UDP DNS are outside the tunnel; this is not
a full-traffic VPN or a guarantee against IP/DNS leaks. A configured relay never
falls back to a direct TCP connection on upstream failure. Launching directly
from Android Studio does not use this repository's proxy file.

Override the default with `--proxy-file PATH` or `--proxy VALUE`; prefer a file
to avoid putting credentials in your shell history. `--no-proxy` disables it
for that invocation. A missing explicitly requested file fails setup.

## Create a phone

Preview without creating or changing a device:

```sh
./setup_galaxy_s25_avd.sh --dry-run --yes
```

Run the wizard:

```sh
./setup_galaxy_s25_avd.sh
```

It proposes a fresh `Galaxy_S25_DATE_RANDOM` name and asks for resources and,
when signup is enabled, profile name/gender. Existing AVD names and backup
directories are rejected. Setup creates the AVD, patches its private ramdisk,
completes Magisk setup, applies the lab profile, installs requested apps,
configures fixtures and mount isolation, runs the checker, and opens signup
when Bumble is installed and a terminal is attached.

For a device-only run without the optional app or signup:

```sh
./setup_galaxy_s25_avd.sh --non-interactive --no-apps --no-bumble-signup
```

For explicit resources and an app package:

```sh
./setup_galaxy_s25_avd.sh --name My_Test_Phone --ram 6144 --cores 6 \
  --vsync 120 --app /absolute/path/app.xapk --yes
```

`--non-interactive` skips terminal signup and prints a resume command. `--yes`
skips setup confirmation but can still enter the signup wizard with a terminal.
`--no-apps` skips external app installation; `--no-checker` independently skips
the diagnostic app. Use `--help` for fixture opt-outs. The default checker must
be built even for a `--no-apps` run unless `--no-checker` is supplied.

AVDs live under `ANDROID_AVD_HOME` or `$HOME/.android/avd`. Backups, logs and
per-device generated fixtures live under `$HOME/galaxy_s25_avd_backups/NAME/`.
Setup prints the actual AVD name, ADB serial, report location and elapsed time.

## Restart and resume

Retain the existing AVD; never rerun creation with its name. For a full restart,
close its window or run `adb -s SERIAL emu kill`, then:

```sh
python3 emulator_proxy.py --avd YOUR_AVD_NAME
```

This uses the current local proxy file. Changing the file requires a full
emulator restart; an Android-only `adb reboot` retains the existing host relay.
Keep the launch terminal/process alive while using the phone.

To verify routing, open an HTTPS public-IP lookup in the guest browser and
compare it with the expected proxy exit. `adb -s SERIAL shell settings get
global http_proxy` should remain unset (`null`) when only this host proxy is
used. A successful host-side proxy request alone does not verify guest routing.

Resume onboarding on that phone:

```sh
python3 bumble_signup.py --serial emulator-5554 --avd YOUR_AVD_NAME \
  --output .local/signup-status --profile-name Alex --profile-gender Woman
```

Use the serial from `adb devices` and confirm the name with
`adb -s SERIAL emu avd name`. Existing app data is retained. Phone and SMS inputs
are hidden terminal prompts and held in memory. `/quit` or Ctrl-C stops signup.
Unknown screens pause for manual handling. The default endpoint is **Open
camera**; selfie capture and submission remain manual. No swipes or messages
are automated. See [signup behavior](bumble-signup/README.md).

The optional signal controller stops when the emulator disconnects. To restart
it after a later launch, use the per-device JSON produced during setup:

```sh
python3 emulator_signal_sim.py --avd YOUR_AVD_NAME \
  --profile "$HOME/galaxy_s25_avd_backups/YOUR_AVD_NAME/setup/profile/device-profile.json" --background
```

## Instructions for an agent

1. Read this README and [SETUP.md](SETUP.md); inspect `--help` and run a dry run.
   Check SDK paths, free space, rootAVD, checker build, and required local inputs.
2. Keep secrets and account/media captures in ignored local directories. Do not
   print `emulator_proxy.py --resolve`: its output contains credentials.
3. Use the creation script for new phones and `emulator_proxy.py` for later
   launches. Identify the exact AVD and serial before any ADB action, especially
   when more than one device is running. Verify the guest exit IP after proxy
   changes. The standalone lab script can launch an AVD directly, so start the
   proxy launcher first when proxy routing is required.
4. The lab script restricts modifications to an allowlist. For an existing
   phone, explicitly opt it in with `S25_LAB_ALLOW=YOUR_AVD_NAME` and pass
   `--avd YOUR_AVD_NAME --action status` (or the intended action). Creation
   handles this for the AVD it creates. Do not expand the allowlist globally.
5. Treat current screen evidence as authoritative during signup. Ask the user
   for missing interactive inputs; do not invent phone/SMS credentials or
   claim photo/ID verification succeeded. Pause at the manual camera endpoint.
6. After code changes, run the tests and relevant syntax/build checks below.
   Test a clean export so ignored workstation files cannot mask missing inputs.
   Describe remaining emulator indicators and failures accurately.

## Tests and project map

```sh
python3 -m unittest discover -s tests -v
for script in *.sh device-checker/*.sh graphics-profile/*.sh; do
  bash -n "$script" || exit 1
done
```

Tests use sanitized UI fixtures and synthetic temporary files, with no account
or device interaction. The relay integration test needs permission to bind a
loopback socket. A restricted sandbox may need that network permission.

| Path | Purpose |
| --- | --- |
| `setup_galaxy_s25_avd.sh`, `setup_options.sh` | Creation, prompts, validation and orchestration. |
| `galaxy_s25_avd_lab.sh` | Existing-device identity profile, inventory, status and restore actions. |
| `emulator_proxy.py` | Proxy validation, host relay, and existing-AVD launcher. |
| `setup_*.py`, `prepare_modem_config.py` | Root/UI/network setup and private modem configs. |
| `device_*.sh`, `generate_lab_profile.py`, `emulator_signal_sim.py` | Boot services, per-device telemetry and host signal controller. |
| `build_file_aliases.py`, `patch_sensor_labels.py`, `provision_file_profiles.sh`, `graphics-profile/` | Validated overlays and graphics-label build sources. |
| `device-checker/` | Offline Android diagnostic app source/build instructions. |
| `bumble_signup.py`, `bumble-signup/*.json` | Interactive onboarding and prompt/default data. |
| `tests/`, `fixtures/` | Regression tests, sanitized UI evidence and metadata policy. |
| `REPORT.md` | Historical lab observations, not a claim about a newly created device. |

For camera modes, diagnostics, resume details, and troubleshooting, read
[SETUP.md](SETUP.md) and the [checker README](device-checker/README.md).
