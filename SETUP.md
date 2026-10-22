For prerequisites, a fresh clone, private local inputs, and agent instructions, start with [README.md](README.md).

Run from this directory:

```sh
./setup_galaxy_s25_avd.sh
```

Host-side proxy: setup automatically reads `.local/emulator-proxy` when present.
This local, Git-ignored file contains one line: `host:port:user:password` or
`http://user:password@host:port`. Keep its permissions at `600`. The configured
proxy is reached through a loopback relay on the Mac on every setup launch;
no Android proxy setting, VPN app or certificate is installed. Setup previews and
launch command logs and the emulator's process arguments do not contain the
credentials. The relay normalizes HTTP/1.0 CONNECT responses for compatibility
with netsim and stops with the emulator. It never falls back to direct TCP.

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
graphics vendor/renderer labels, Magisk isolation for Bumble and Device Red
Flags, and removal of the manager APK. The local checker is installed, opened
and its report saved under the phone's `setup/checker-report.json` backup path.
Reports retain remaining findings; a clean scan is not assumed.

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

Before opening Bumble, the helper requires Android to report a validated
default network. If none exists, it enables Wi-Fi, connects the emulator's
visible open `AndroidWifi` access point, and waits for validation. It does not
connect to other Wi-Fi networks. A cellular signal console response alone is
not considered internet connectivity.

Creation also copies the SDK's `data/misc/modem_simulator` source configs beside
the private ramdisk. The emulator resolves that directory relative to its
selected ramdisk; missing files can disable modem startup. See the
[emulator implementation](https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android-qemu2-glue/main.cpp).
Existing phones repaired with `prepare_modem_config.py` need a full emulator
cold restart to create the modem transport; an Android-only reboot cannot do so.

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
installed emulator advertises this camera mode. Relative paths are converted
to absolute paths. Keep the file at that location: its path is saved with the
AVD and passed to every setup launch. Paths with spaces are supported when quoted.
The recording is a camera source, separate from the four profile-photo uploads.
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

`--app FILE` is repeatable. By default, APK/XAPK files beside the script are
installed. `--no-apps` skips these; `--no-checker` separately skips the diagnostic
APK. Use `--help` for individual fixture opt-outs. `--keep-file-paths` also
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
