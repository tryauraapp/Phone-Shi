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
  prefers `$SDK/platforms/android-35/android.jar`, falling back to the newest
  installed numeric API 35+ platform. Set `ANDROID_JAR` to override it explicitly.

SDK lookup order is `ANDROID_SDK_ROOT`, `ANDROID_HOME`, then
`$HOME/Library/Android/sdk`. Export the tools before following the examples:

```sh
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
```

Install the required image and tools through Android Studio's SDK Manager or
its `sdkmanager` CLI:

For the CLI, install **Android SDK Command-line Tools (latest)** in SDK
Manager's **SDK Tools** tab first. Accept the licenses with
`sdkmanager --licenses` on the destination Mac.

```sh
sdkmanager 'platform-tools' 'emulator' 'build-tools;36.0.0' 'platforms;android-35' \
  'system-images;android-35;google_apis_playstore;arm64-v8a'
```

Keep at least 8 GB free per new phone. The default allocation is 4096 MB RAM
and four CPU cores. Setup looks for rootAVD at `$HOME/Downloads/rootAVD` and
offers to clone `https://github.com/galihlasahido/rootAVD.git` when absent.
Override its location with `ROOTAVD_DIR` and its source with `ROOTAVD_REPO`.
This external dependency and any downloads it performs need network access.

## Another Mac / device missing in Android Studio

Clone this repository on an **Apple Silicon Mac**, install the prerequisites
above, and use the SDK location shown in Android Studio's **Settings > Android
SDK**. A clone contains the scripts, not existing virtual phones, app sessions,
SDK images, signing keys, proxy credentials or personal media.

Start with the read-only doctor:

```sh
python3 mac_avd_doctor.py
```

It checks SDK tools and lists registrations and unregistered `.avd` directories
in the standard and environment-selected Android locations. A terminal can
inherit `ANDROID_AVD_HOME` while Android Studio launched from the Dock does not;
that mismatch can make a valid phone disappear from Device Manager.

For an existing phone, diagnose and register it in Studio's usual directory:

```sh
python3 mac_avd_doctor.py --avd YOUR_AVD_NAME
python3 mac_avd_doctor.py --avd YOUR_AVD_NAME \
  --avd-dir /absolute/path/YOUR_AVD_NAME.avd --register
```

Registration writes `~/.android/avd/YOUR_AVD_NAME.ini`, backing up an existing
pointer before repair. It preserves device data and refuses to replace a name
that points to another existing device. Restart Android Studio and open
**Tools > Device Manager > Virtual**. For a deliberately customized Studio
environment, pass `--studio-avd-home PATH`; pass `--sdk PATH` to diagnose its SDK.
Exit status `0` means discovery checks passed, `1` means checks need attention,
and `2` means invalid inputs or a command/read/write failure. A registration can
be repaired successfully while other checks still return `1`.

If there is no existing `.avd` directory on the new Mac, build the checker and
create a new phone using the instructions below. **Do not reuse the name of an
existing phone to repair discovery.** Use the repository launcher for these lab
phones; Android Studio's Play button omits their private engine/proxy options.

Copying a lab phone from another Mac needs more than registration: private
engines have SDK symlinks and the identifier manifest contains a host path.
The doctor reports missing images, host media paths, engine paths and broken
SDK links; it does not rewrite engines or migrate account sessions. Create a
fresh phone on the new Mac for the supported workflow. Keep old AVDs and local
identifier registries backed up privately. See [detailed troubleshooting](SETUP.md#device-not-found-on-another-mac).

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
| Google account | Interactive Google Play sign-in installs Bumble; credentials are prompted privately and not saved. |
| Optional APK/XAPK files | Extra apps only when explicitly passed with `--app PATH`; files beside the script are not automatically installed. |
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

### Automatic per-phone NodeMaven proxies

To give every newly created phone its own verified NodeMaven session, save a
current NodeMaven API key as `.local/nodemaven-api-key` with permissions `600`.
Do not pass the key on the command line. When that file exists and no explicit
proxy option is supplied, setup performs the following before creating the AVD:

1. Reads the account's proxy credentials through the NodeMaven API.
2. Looks up current US Mobile inventory and selects the T-Mobile carrier code,
   preferring inventory marked High.
3. Requests a unique no-rotation session targeted to the selected city and uses
   NodeMaven's Quality filter.
4. Uses NodeMaven's proxy check to require a matching US/T-Mobile exit.
5. Saves the private proxy under the phone's backup `setup` directory with
   permissions `600`. Later `emulator_proxy.py --avd NAME` launches select it
   automatically.

NodeMaven calls the highest-quality filter **Quality** in its dashboard, but its
documented username spelling is `-filter-medium`. `-filter-high` is not a valid
replacement; “High” on locations and carriers is an inventory-availability
badge. An expired key, missing T-Mobile inventory, failed proxy authentication,
or mismatched exit aborts setup before the AVD is created. Explicit `--proxy`,
`--proxy-file`, and `--no-proxy` options always take precedence. To use a key
stored elsewhere, pass `--nodemaven-key-file PATH`.

The saved session remains targeted to the selected city. A mobile exit IP may
change without invalidating the phone: later launches accept a replacement when
it remains on the saved carrier, state and time zone and within 100 miles of the
saved home centre. Nearby municipality labels are accepted because IP
geolocation is approximate. A different state, time zone, carrier or distant
exit blocks the launch instead of silently changing the phone's home profile.

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
completes Magisk setup, applies the lab profile, signs into Google Play and
finishes the battery, signal and proxy-derived GPS profile, installs Bumble
without opening it (plus any explicitly requested local apps), activates mount
isolation with a reboot, verifies the complete phone, and only then opens Bumble
for signup when a terminal is attached.

Google sign-in selects personal use and skips optional recovery and address
entry. Google security checks remain manual. Non-interactive runs print a
Google Play resume command. `--no-play-store` skips only the Google Play step.

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

For a completed phone this is a managed, fail-closed restart: it selects the
phone's saved proxy, verifies the exit IP/location, reapplies the proxy-derived
time zone and private launch identity, then restores and verifies LTE, battery,
signal, bounded GPS, saved display preferences, root isolation and certified
app state after Android boots. A configured video camera also gets a real
Camera2 motion check rather than trusting a saved flag or first frame.
Direct Android Studio launch bypasses that restoration. Changing a proxy file
requires a full emulator restart; an Android-only `adb reboot` retains the
existing host relay. Keep the launch terminal/process alive while using the
phone.

Proxy launches append redacted JSON lines to `.local/proxy-diagnostics.jsonl`
(owner-only permissions). Override the location with `--diagnostics-file PATH`.
Events use opaque connection IDs and report UTC time, TCP/CONNECT timings,
upstream CONNECT status codes, transfer byte counts, and fixed error categories.
For example, an upstream `407` is recorded as `status_code: 407` even though the
emulator receives a generic `502`. Timeout stages distinguish `client_headers`,
`upstream_tcp`, and `upstream_connect`; transfer failures use `tunnel`.
No destination names, request URLs, headers, credentials, payloads, or exception
messages are recorded. Encrypted origin HTTP responses remain invisible to the
relay: a CONNECT `200` does not prove that a CAPTCHA image downloaded.
Restart the full host emulator process to load relay code changes; an Android
guest reboot alone keeps the old relay. Diagnostic files append until removed
or rotated by the operator. Diagnostic write errors do not stop the relay.

If setup stops at shell authorization (step 7), retain the phone and run its
bounded permission helper after Android finishes booting:

```sh
python3 setup_su.py --serial emulator-5554 --avd YOUR_AVD_NAME \
  --output .local/shell-diagnostics --timeout 180
```

The helper verifies the AVD identity, opens Magisk, and distinguishes a grant,
denial, timeout, or device disconnect. Each root request has a device-side
35-second timeout and a host-side limit. A stalled request saves screenshots,
UI XML, process state, and Magisk logs before one manager restart and retry.
Diagnostics have their own bounded capture time. A successful helper verifies
UID 0; it does not automatically resume the remaining creation stages.

To verify routing, open an HTTPS public-IP lookup in the guest browser and
compare it with the expected proxy exit. `adb -s SERIAL shell settings get
global http_proxy` should remain unset (`null`) when only this host proxy is
used. A successful host-side proxy request alone does not verify guest routing.

Resume onboarding on that phone:

```sh
python3 bumble_signup.py --serial emulator-5554 --avd YOUR_AVD_NAME \
  --output .local/signup-status --profile-name Alex --profile-gender Woman
```

Signup is fail-closed. The creation workflow writes
`setup/setup-complete.json` only after all required setup artifacts exist, the
checker reports zero red flags with the expected cellular/root-isolation
evidence, and the live phone passes its AVD, boot, ARM64 and Galaxy S25 checks.
Each signup helper verifies that certificate, its immutable artifact hashes,
the installed app, working shell root and that app's Magisk isolation before it
can begin. This permits a non-interactive phone build to finish before the app
is installed, but never permits signup in that pending state.
Deleting or changing certified evidence, using another AVD, or running an app
that was not certified blocks signup. Read-only POF screen observation remains
available without the certificate.

Use the serial from `adb devices` and confirm the name with
`adb -s SERIAL emu avd name`. Existing app data is retained. Phone and SMS inputs
are hidden terminal prompts and held in memory. `/quit` or Ctrl-C stops signup.
Unknown screens pause for manual handling. The default endpoint is **Open
camera**; selfie capture and submission remain manual. No swipes or messages
are automated. See [signup behavior](bumble-signup/README.md).

To build a fresh phone with Plenty of Fish instead, select the POF path:

```sh
./setup_galaxy_s25_avd.sh --pof-signup --camera-video /absolute/path/to/this-phone.mp4
```

This installs the official `com.pof.android` package from Google Play, adds it
to the root-isolation configuration, and starts the guarded screen recorder.
It can apply explicitly authorized notification and foreground-location
permissions, then pauses for direct review at profile choices, terms,
credentials, SMS, photos, CAPTCHA, and identity checks. See the
[recorded POF flow](pof-signup/README.md).

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
```

Swap one phone's camera clip (closes and relaunches that phone only):

```sh
python3 swap_camera_video.py --avd NAME --video /path/new.mp4 --restart
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
| `mac_avd_doctor.py` | Read-only Mac/SDK discovery diagnostics and explicit, backed-up AVD registration repair. |
| `setup_*.py`, `prepare_modem_config.py` | Root/UI/network setup and private modem configs. |
| `phone_setup_guard.py` | Fail-closed setup certificate creation and pre-signup verification. |
| `device_*.sh`, `generate_lab_profile.py`, `emulator_signal_sim.py` | Boot services, per-device telemetry and host signal controller. |
| `build_file_aliases.py`, `patch_sensor_labels.py`, `provision_file_profiles.sh`, `graphics-profile/` | Validated overlays and graphics-label build sources. |
| `device-checker/` | Offline Android diagnostic app source/build instructions. |
| `bumble_signup.py`, `bumble-signup/*.json` | Interactive onboarding and prompt/default data. |
| `pof_signup.py`, `pof-signup/` | Sanitized POF screen mapping and guarded permission/capture helper. |
| `tests/`, `fixtures/` | Regression tests, sanitized UI evidence and metadata policy. |
| `REPORT.md` | Historical lab observations, not a claim about a newly created device. |

For camera modes, diagnostics, resume details, and troubleshooting, read
[SETUP.md](SETUP.md) and the [checker README](device-checker/README.md).
