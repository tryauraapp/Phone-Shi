For prerequisites, a fresh clone, private local inputs, and agent instructions, start with [README.md](README.md).

## Device not found on another Mac

Use a native Apple Silicon terminal. Install Android Studio and select the
same SDK directory in both Studio and the terminal:

```sh
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
python3 mac_avd_doctor.py
```

If your SDK lives elsewhere, substitute Studio's actual SDK path. Install the
Google Play API 35 ARM64 image, platform 35 and build tools 36.0.0 from the
README. Accept SDK licenses locally with `sdkmanager --licenses`. A JDK must
be available to `java`, `javac`, `jar` and `keytool`; if using Studio's bundled
JDK, set `JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"`
and prepend `"$JAVA_HOME/bin"` to `PATH`. Run `bash device-checker/build.sh`.

The creation and proxy launcher scripts use `ANDROID_AVD_HOME` when set,
otherwise `~/.android/avd`. Studio started from the Dock may not inherit your
terminal's exports. The doctor also inspects the locations selected by
`ANDROID_USER_HOME` and `ANDROID_EMULATOR_HOME`; if those disagree, use an
explicit `ANDROID_AVD_HOME` for terminal launches and register in Studio's
actual discovery directory.

For an existing folder that Studio cannot find:

```sh
python3 mac_avd_doctor.py --avd YOUR_AVD_NAME \
  --avd-dir /absolute/path/YOUR_AVD_NAME.avd --register
```

This repairs the `.ini` discovery pointer, not the virtual disk. Existing
registrations are backed up beside the `.ini`; conflicting live registrations
are refused. To undo, restore the printed backup, or remove only the newly
created registration if none existed. Keep the `.avd` folder. Restart Studio
and check **Tools > Device Manager > Virtual**. The helper verifies discovery
with the SDK's `emulator -list-avds` under the selected Studio AVD home, but it
cannot inspect the environment of a separately launched Studio process.

If a phone still does not appear, run the doctor with `--sdk` matching Studio
and `--studio-avd-home` matching its custom environment. If the phone appears
but will not boot, read the reported image/host path/private engine findings.
The helper does not delete lock files, wipe user data, modify system images,
regenerate identifiers, launch emulators or bypass macOS security prompts.

For a fresh clone with no phone data, create a new phone. An AVD is not included
in GitHub. For copied lab phones, registration alone cannot repair the private
engine's old SDK symlinks, absolute manifest path, SDK version compatibility,
or missing host camera files. Preserve the original and create a fresh device
on the destination Mac. Install a compatible SDK: this project's engine
patches validate supported binary layouts and stop on unsupported versions;
an arbitrary future Emulator release is not guaranteed to work.

After discovery succeeds, launch the lab phone with:

```sh
python3 emulator_proxy.py --avd YOUR_AVD_NAME
```

Use `ANDROID_AVD_HOME=/path/to/registrations` for that command if its default
differs from the registration directory. Studio's launcher omits this lab's
private engine and proxy settings. Supply private proxy/media inputs locally;
they are intentionally absent from GitHub.

## Creation and configuration

Run from this directory:

```sh
./setup_galaxy_s25_avd.sh
```

Host-side proxy: setup automatically reads `.local/emulator-proxy` when present.
If `.local/nodemaven-api-key` exists and no explicit proxy option is supplied,
setup instead provisions a separate city-targeted, no-rotation US Mobile/T-Mobile NodeMaven session
for the new phone, verifies the targeted exit through NodeMaven, and stores the
private result in that phone's backup. Future `emulator_proxy.py --avd NAME`
launches select the same per-phone proxy automatically and apply its saved
proxy-derived time zone on every cold start. A changed mobile exit IP is allowed
when the carrier, state and time zone still match and its reported coordinates
remain within 100 miles of the saved home centre; nearby municipality labels do
not fail the check. A proxied phone refuses to launch if that location record is
missing, invalid, or conflicts with an explicit `-timezone` argument. The API key and saved
proxy files must remain owner-readable only and are never copied into the AVD.
This local, Git-ignored file contains one line: `host:port:user:password` or
`http://user:password@host:port`. Keep its permissions at `600`. The configured
proxy is reached through a loopback relay on the Mac on every setup launch;
no Android proxy setting, VPN app or certificate is installed. Setup previews and
launch command logs and the emulator's process arguments do not contain the
credentials. The relay normalizes HTTP/1.0 CONNECT responses for compatibility
with netsim and stops with the emulator. It never falls back to direct TCP.

New phones resolve their GPS center and time zone from the configured proxy's
exit IP before AVD creation. The HTTPS geolocation request goes through that
authenticated proxy and never falls back to a direct connection. A failed
lookup stops setup; dry-runs skip the network request. The result is saved to
`~/galaxy_s25_avd_backups/NAME/setup/proxy-location.json`. IP geolocation is
approximate. With `--no-proxy`, the fallback is Newark, New Jersey (`40.7357`,
`-74.1724`, `America/New_York`). Setup enables device location and sends a GPS
fix after startup and setup reboots, before app onboarding.
After the final setup reboot, a host GPS controller moves 20–30 feet in a
random direction every 3–5 seconds. Each fix stays within 1,000 feet of the
original startup center; outward steps at the boundary are redrawn. The
controller stops on disconnect or AVD identity change. Setup prints its restart
command for later launches and saves the latest fix in
`~/galaxy_s25_avd_backups/NAME/setup/location/location-state.json`.
The startup center stays fixed throughout that creation run, even if the
upstream proxy later rotates its exit IP.

Every new AVD reserves its own synthetic IMEI (with a Luhn check digit), serial
number, 16-character Android ID, locally administered unicast Wi-Fi/cellular
MAC addresses and private `/23` network in `.local/device-identifiers.sqlite3`.
Unique database constraints prevent reuse across creation runs; keep this local
registry when moving the project. The AVD stores its stable values in
`s25-identifiers.json`. Setup creates private, signed emulator engines for that
AVD to change the modem's hardcoded IMEI, leaving the SDK engines untouched.
After rooting, setup also installs a per-device Magisk overlay for the Android
15 reference radio HAL. Its `getImei` method has a separate compiled-in stock
value; changing only the host modem does not change Android's reported IMEI.
The overlay changes only the validated immediate fields that construct this
15-digit value. Unknown library layouts are rejected and the original is kept.
The launcher reloads that private engine and serial on subsequent starts.
Unsupported engine layouts stop setup rather than sharing a stock IMEI.
The private engines also synchronize the modem's reported IPv4 address,
gateway and DNS with the assigned radio subnet. Changing only the virtual
router leaves Android using the modem's hardcoded `10.0.2.15` and breaks data.
The supported ARM64 modem function layouts are checked before patching; an
unknown engine layout stops setup. The emulator's subnet option allowlist does
not include `dns=`, so the router uses its subnet-derived DNS address.
Use `emulator_proxy.py` to launch these AVDs; Android Studio's normal launcher
does not apply their private engine or serial options.

Setup initializes the user-0 secure Android ID before app installation and
checks it, the serial and the Android telephony-service IMEI after setup
reboots. Results are saved as `identifiers-verified.json` in the setup backup
directory. Apps on Android 15 receive signing-key/user-scoped Android IDs from
their fresh per-device user data; those can differ from the user-0 secure value.
These are emulator test identifiers, not manufacturer-assigned hardware IDs.

The CPU architecture is already ARM64: setup uses the `arm64-v8a` system image
and `hw.cpu.arch=arm64`. Each setup launch and final setup reboot verifies
`ro.product.cpu.abi=arm64-v8a` and `uname -m=aarch64`, stopping on a mismatch.
The Samsung profile reports `QTI` / `SM8750` for the SoC. CPU implementer
spoofing is disabled; `/proc/cpuinfo` retains the kernel's actual implementer.
Remaining CPU findings stay in the checker report and do not stop setup.

Wi-Fi is disabled and the simulated SIM uses LTE-only mode. The launcher splits
each reserved network into separate radio/Wi-Fi `/24` subnets and configures
the virtual DHCP, router and DNS addresses. Its radio interface gets the reserved
cellular MAC through QEMU. The boot service applies the reserved Wi-Fi MAC if
`wlan0` exists while keeping Wi-Fi off. Setup checks active network addresses,
MAC read-backs, Android's validated cellular default network and LTE radio type.
The checker also reads cellular transport and LTE through Android APIs. There
is no Wi-Fi recovery fallback. This is a simulated LTE connection backed by the
host network and configured TCP proxy, not a physical mobile subscription.

All phones keep the same Galaxy S25 / Android 15 hardware profile. Each stores
separate persistent brightness, display timeout, haptic and font settings.
Preferences are not identifiers: changes made by Android or the emulator are
recorded under `settings_drift` and do not stop identifier verification.
Its manifest also exports a unique S25/Android-15 test User-Agent with a profile
suffix. **That UA is not applied to Bumble:** the app constructs its own headers
and has no device-wide UA override. `user_agent_status` records this limitation;
the exported string is not claimed to match the app's outgoing requests.

Override it with `--proxy-file PATH` or `--proxy VALUE`, or use `--no-proxy` to
disable it for a run. To start an existing phone with the same default proxy:

```sh
python3 emulator_proxy.py --avd YOUR_AVD_NAME
```

The launcher accepts the same proxy options and additional emulator arguments.
Launching directly through Android Studio does not use this local file.
The emulator proxy tunnels TCP only; UDP (including QUIC and UDP DNS) is not
covered. This is not a full-traffic VPN or a guarantee against IP/DNS leaks.
Reference: [Android Emulator proxy documentation](https://developer.android.com/studio/run/emulator-networking-proxy).

The terminal wizard proposes a fresh `Galaxy_S25_DATE_RANDOM` name and asks for
the device name, RAM, CPU cores and refresh rate, plus the Bumble profile first
name and gender when signup is enabled. The profile name is separate from the
device name. Android Studio shows the device name with spaces. Press Enter to
keep a default. Existing AVDs, registrations and
backup directories are rejected; nothing is overwritten. Each phone has its own
ramdisk, telemetry seed, vendor-library backups, generated fixtures and logs.

Defaults include Samsung build identity and display settings, late-boot QEMU
properties, sensor labels, randomized battery with ongoing drift, randomized
modem signal, vendor file aliases/config visibility, QEMU metadata visibility,
graphics vendor/renderer labels, Magisk isolation for the selected signup app and Device Red
Flags, and removal of the manager APK. The local checker is installed, opened
and its report saved under the phone's `setup/checker-report.json` backup path.
Reports retain remaining findings; a clean scan is not assumed.

Signup cannot start merely because the earlier commands ran in order. After the
final checker pass, setup creates `setup/setup-complete.json` only when the
required setup evidence is present, the checker has zero red flags and confirms
the expected LTE/root-isolation result, and the live device still matches its
AVD and ARM64 Galaxy S25 profile. Bumble, Tinder and POF revalidate the
certificate, immutable evidence hashes, live state, installed signup package,
shell root and app-specific Magisk denylist before their full signup runner
begins. A non-interactive setup can therefore certify the phone before later
app installation, while the helper remains blocked until package isolation is
also ready. A missing, stale or app-mismatched certificate stops the helper
with no signup tap.

Every later cold start must use `emulator_proxy.py --avd NAME`. For a certified
phone, the launcher verifies that the live proxy remains on the saved carrier,
state, time zone and geographic boundary; a city-targeted mobile IP may rotate.
It then launches with the private
engine, serial, network identity, ramdisk, camera profile, graphics workaround
and saved time zone. Once Android boots, `restore_phone_runtime.py` revalidates
the certificate and live device identity, restores LTE, checks the persistent
battery service, restores the saved brightness/timeout/haptics/font choices,
enables location, and starts fresh per-phone signal and bounded-GPS controllers.
Phones with a configured video camera also run the saved Camera2 motion probe;
the saved flag or first frame alone is not accepted as playback proof.
The emulator is closed if restoration fails; a partly restored phone is never
reported ready. Android Studio's direct play button bypasses this startup gate.
State-replacing cold-start flags such as `-wipe-data`, snapshots, alternate
camera/GPU/data images, identity/network overrides, or a GL sync override are
rejected for certified phones; ordinary UI/logging flags remain available.

For Tinder, `--tinder-signup` now joins Google Play install, isolation,
certification and first launch to the same phone setup. Reviewed onboarding
choices are explicit setup flags: notification allow/decline, Tinder Terms,
SMS terms, House Rules, gender and visibility, relationship goal, and foreground
location. When all are supplied, the runner applies the learned screens and
pauses before private phone, SMS, name and birth-date entry. Consents are never
silently reused for another account.

After the final device check, setup launches the interactive Bumble signup
wizard when Bumble is installed. It reuses the profile name and gender chosen
during creation, and randomly chooses **four distinct photos** from the local
images you supply in `bumble-signup/photos/` (at least four are required). The video is excluded;
there is no photo-path prompt. Each helper invocation draws a new set. If photos
are already uploaded on a resumed phone, they are retained.

Saved choices in `bumble-signup/profile-defaults.json` are applied without
questions: photo-verification endpoint, United States, birthday January 28,
2007, gender shown on profile, recovery email skipped, and dating intention
Open to seeing where things go. Edit that file to change these defaults; the
saved birthday must be for an adult. These are example defaults; review them for each profile.
The national phone number is requested **only when Bumble reaches phone entry**.
The SMS code is requested at code entry; neither is saved as a default.
Dating preference defaults to Men for Woman profiles and Women for Man
profiles; Nonbinary profiles are asked which genders to meet. Five interests
are randomly selected and confirmed as `5/5 selected`. Two different prompt
questions and answers are drawn from `bumble-signup/prompt-pool.json`, containing
three answers for each of the 52 questions mapped on the device (156 total).
The picker switches between Date night, Looking for, About me, Real talk,
Bit of fun and Self-care, then scrolls the question list separately from the tabs.
Both selected answers must be saved before continuing. Phone, email and SMS inputs are hidden in the
terminal. Details are held in memory;
they are sent to the app but are not written to setup logs or status files.

The helper uses the screen mappings documented in `bumble-signup/README.md`;
sanitized XML regression evidence is in `tests/fixtures/bumble-signup/`. It skips optional height, habits, family plans, beliefs,
passkey and marketing screens, uploads your supplied photos, and accepts the
community guidelines. Location and notifications are enabled through the app
prompts. Precise location and notification permission grants are checked before
reporting completion. Review your details before continuing: Bumble confirms the birthday
as an age that cannot be changed later.

By default, it proceeds through Profile → Complete Profile → Verification →
Get photo verified and stops at **Open camera**. You complete the selfie yourself
in the emulator. Set `verification` to `false` in the defaults file for an
endpoint before **Start connecting**.
The default path closes that sheet to reach the profile tab; no swipes or
messages are performed. Signup completion does not mean photo/ID verification
has succeeded.

Unknown screens, disabled controls, unsupported text input and app errors pause
for you to handle the screen in the emulator. Enter resumes inspection;
`/quit` or Ctrl-C stops signup and keeps the phone/app data. The automation
does not automatically request another SMS or repeat a submitted step. A
non-ASCII name or answer can be entered manually at its screen. On an existing
phone with other library images, select your supplied photos manually if the
picker cannot identify the staged set.

At the SMS prompt, paste/type six digits, enter `/mac` to use the Mac clipboard,
or press Enter to attempt pasting the device clipboard. Clipboard contents must
be a six-digit code; other Mac clipboard content is rejected. Current Bumble
can expose only the PIN container in accessibility, so the helper supports that
as well as individual digit controls. For SMS submission, the helper saves
the Continue arrow's Android coordinates before entering the code and refreshes
them whenever the SMS hierarchy is available. If the accessible button stays
disabled or the post-entry UI read fails, it taps that saved position. While
the SMS screen persists, submission is retried every 10 seconds without asking
for or typing the code again, or requesting another SMS. Recognized navigation
away from SMS clears the pending submission.
Other Continue/save actions dismiss a visible
keyboard before re-reading button bounds. Error screenshots use the macOS
emulator-window capture helper, because protected Android captures may be black.
These screenshots can contain the personal details visible in the app.

Before opening Bumble, the helper disables Wi-Fi, enables simulated mobile
data and requires Android to report a validated cellular default network with
LTE radio registration. It does not fall back to Wi-Fi. A successful cellular
signal console response alone is not considered internet connectivity.

Creation stages the SDK's `data/misc/modem_simulator` source configs under
`AVD/s25-system/data/misc/modem_simulator`. Before each launch, the launcher
copies the AVD's current `ramdisk.img` to `AVD/s25-system/ramdisk.img` and selects
it explicitly. This location survives first-boot cleanup of `AVD/data`, while
still picking up rootAVD's patched ramdisk on later launches. The emulator
resolves modem source configs relative to the selected ramdisk; missing files
disable modem startup even though Android itself can boot. See the
[emulator implementation](https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android-qemu2-glue/main.cpp).
Existing phones repaired with `prepare_modem_config.py` need a full emulator
cold restart to create the modem transport; an Android-only reboot cannot do so.

For a phone created before this repair, keep the existing AVD and identifiers.
Stage modem sources with `prepare_modem_config.py --system-image IMAGE_DIR
--avd-dir AVD_DIR --lte-only`, update its private engines with
`device_identifiers.py --avd-dir AVD_DIR --sdk SDK_DIR --repair-network`, and
cold-start it through `emulator_proxy.py`. No userdata wipe is required.
LTE selection and validation work before root; MAC and identifier checks that
read root-protected files still run after Magisk setup.

For a live front camera, first run `emulator -webcam-list`, then create with
`./setup_galaxy_s25_avd.sh --front-camera webcamN` using the listed camera number.
The selected source is saved in the AVD and passed to each setup launch. Camera numbering varies by host; inspect the current list. macOS may ask you to grant Camera
access. This uses the emulator's
[host-webcam support](https://developer.android.com/studio/run/emulator-commandline#common).
Changing the camera source of a running phone requires a full emulator restart.
Selfie capture and submission are completed by you in Bumble.

The front camera can also read a local recording using the emulator's
[`videofile:` camera source](https://developer.android.com/studio/run/emulator-commandline#common).
Copy the recording from your Android phone onto the Mac, then select it when
creating the new emulator:

```sh
./setup_galaxy_s25_avd.sh --front-camera "videofile:/absolute/path/phone-video.mp4"
```

Put your optional recording at `bumble-signup/camera/phone-video.mp4`.
Personal media is local and excluded from Git; a fresh clone has no recording.
The main `setup_galaxy_s25_avd.sh` automatically selects this recording when
that file exists, including its normal rooted-device setup and subsequent
launches. An explicit `--front-camera` overrides this default, for example
`--front-camera emulated` or `--front-camera webcam0`.
Create a new emulator with this recording preselected by running
`bash setup_video_camera.sh`. It forwards additional setup options, for example
`bash setup_video_camera.sh --name My_New_Phone`. Use
`bash setup_video_camera.sh --dry-run --yes` to preview without creating a device.
The file stays on the Mac; it is not pushed into Android storage.

The script checks that the file exists, is readable and nonempty, and that the
installed emulator advertises this camera mode. For a video source, it now runs
`configure_video_camera.py` before first boot: the original is retained inside
the AVD, and proportionally cropped VP9/WebM plus native environment/animation
settings are saved per phone. This requires `ffmpeg`; the current S25 camera
profile is portrait 3:4. Keep the AVD's `camera/` directory in place. Relative
input paths and quoted paths with spaces are supported. Use the saved native
camera recipe below to configure a different measured preview aspect ratio.
The recording is a camera source, separate from the four profile-photo uploads.
For the verified looping, crop-to-fill setup on an existing S25 emulator, see
[the saved native camera recipe](VIDEO_CAMERA.md). It records the required
animation setting, preview-ratio rule, and renderer-specific framing profile.
It is configured before launch; it does not switch an already-running camera.
The signup helper still stops at **Open camera** for you to review the feed and
complete capture and submission. This does not guarantee Bumble accepts the
recording or completes verification.

To use a still frame instead, extract one at a chosen time (this requires
`ffmpeg`), then select `imagefile:`:

```sh
ffmpeg -n -ss 00:00:02 -i "/absolute/path/phone-video.mp4" -frames:v 1 "/absolute/path/camera-frame.png"
./setup_galaxy_s25_avd.sh --front-camera "imagefile:/absolute/path/camera-frame.png"
```

For an existing AVD, close its emulator window and fully restart it with the
selected camera source; keep your normal launch options, including any private
ramdisk configuration. Do not rerun device creation with the same AVD name.
File validation does not check codec compatibility; inspect the preview in the
Android Camera app before opening verification.

Use `--no-bumble-signup` to omit this step. `--non-interactive` creates the
phone and prints a command to run signup later; `--yes` still permits the
credential wizard when a terminal is attached. `--no-apps` or a custom app list
without Bumble skips signup if Bumble is absent. Resume on an existing phone:

```sh
python3 bumble_signup.py --serial emulator-5554 --avd YOUR_AVD_NAME --output /tmp/bumble-signup-status
```

Use the actual serial and AVD name printed by setup. You can also supply
`--profile-name "Alex" --profile-gender Nonbinary` to either the creation script
or the signup helper. Supported genders are `Woman`, `Man`, and `Nonbinary`.
The printed resume command includes those creation choices. Without them, the
helper asks for name and gender; other details are requested only as needed by
the current app screen. It never clears app data.
Its output directory contains `status.json` with a status and step elapsed
seconds, plus `screenshots/` when a UI error is captured. The creation script prints **Total elapsed** at exit, including phone
creation, rooting, installation, signup, credential prompts and SMS wait time.
Paused or skipped signup is reported explicitly; the phone remains available.

Setup recognizes Android's “isn't responding” dialog by its system Wait button,
selects Wait, and retries reading the screen. UI reads have both guest and host
timeouts; setup waits use elapsed time. If System UI returns to the launcher,
the Magisk setup step reopens the app and also checks whether setup already
completed before waiting for another prompt.
The Magisk confirmation step retries an OK tap when its dialog remains visible
and verifies Android boot completion and the su mount. A sent tap alone is never
treated as a completed setup. Graphics directory and library attributes are
copied explicitly, including SELinux labels required by SurfaceFlinger.

Root isolation enables built-in Zygisk, configures the installed target packages
and reboots before installing the battery loop and starting the host modem
controller. The final scan must explicitly report `Root binaries: NOT OBSERVED`,
and shell `su` must still return UID 0. The setup fails with its saved report if
either verification fails. The root binaries remain available to the shell;
their mounts are removed from the selected apps' namespaces.
After enabling Shell in Magisk, grant verification waits four seconds between
requests. Magisk 30.6 refreshes its three-second permission cache on every su
request, so faster polling can perpetuate a cached denial after a successful
grant.

Preview the choices without modifying anything:

```sh
./setup_galaxy_s25_avd.sh --dry-run
```

Create unattended with a fresh name, or optionally specify an explicit name:

```sh
./setup_galaxy_s25_avd.sh --non-interactive
./setup_galaxy_s25_avd.sh --name My_Test_Phone --ram 6144 --cores 6 --vsync 120 --yes
```

By default, Bumble is installed from Google Play only after the Galaxy S25
identity and battery, signal and proxy-derived GPS profile are active. Google email and
password are requested privately in the terminal and are not saved or logged.
The observed sign-in flow skips optional **Sign in with ease** carrier discovery,
selects personal use, skips optional recovery and home address entry, and disables
basic device backup. Uppercase Google buttons and a return to the signed-in
Play Store home screen are supported. Extra Google security checks
remain manual. Setup waits for installation, verifies Google Play as the installer,
force-stops Bumble without opening it, activates package isolation with a reboot,
restarts and verifies runtime services, and opens Bumble only after the final
checker and setup certificate pass.
Google Play supplies its currently available compatible version.

Local APK/XAPK files beside the script are no longer installed automatically.
`--app FILE` explicitly installs extra local apps and is repeatable. `--no-apps`
skips extra apps and Google Play installation; `--no-play-store` skips only the
Google Play step. `--no-checker` separately skips the diagnostic APK. In
non-interactive runs, Google sign-in/installation is deferred with a resume command.
Use `--help` for individual fixture opt-outs. `--keep-file-paths` also
disables graphics labels because those fixtures share a boot overlay.

The image remains Android 35 / Google Play / arm64-v8a. Graphics fixtures are
built from each new phone's own libraries with clang and SDK build-tools 36.0.0.
The metadata policy is the saved fixture for this fixed image. Binary patchers
reject unrecognized layouts before installing file aliases. Build the checker
with `bash device-checker/build.sh` if its APK is missing.

Battery and guest overlays persist at boot. The modem controller runs on the
Mac and stops when that emulator exits; the setup prints its restart command
for later launches. CPU context and network topology can still be reported.
Graphics labels do not replace the graphics backend, and these local fixtures
do not establish a Play Integrity verdict.

Validation: run `python3 -m unittest discover -s tests -v` and
`for script in *.sh device-checker/*.sh graphics-profile/*.sh; do bash -n "$script" || exit 1; done`.
The proxy integration test needs loopback socket permission.
