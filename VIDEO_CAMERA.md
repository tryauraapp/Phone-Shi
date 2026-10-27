# Saved working front-camera recipe

Verified on 24 October 2026 with Android Emulator 37.2.12 and existing AVD
`Galaxy_S25_20261024_a9690b26` (serial `emulator-5556` during testing).
This uses native emulator video playback: no OBS, virtual macOS webcam, or
persistent ffmpeg feeder. It does not make an emulator a physical phone or
guarantee acceptance by third-party camera/verification apps.

## Current complete workflow (second phone)

The original H264 recipe below saved the geometry, **not a complete reliable
startup path for every AVD**. On `Galaxy_S25_20261024_10f841ca`, the stock Camera
preview remained frozen even when a direct Camera2 ImageReader received
different actual front-camera frames. Do not confuse that display failure
with proof that every camera consumer receives a still image.

The compatibility workflow is now executable code:

```sh
# Fully close ONLY the phone being configured; keep its apps and userdata.
python3 configure_video_camera.py --avd YOUR_AVD \
  --video "/absolute/path/original.mp4" --preview-size 1080x1440

python3 emulator_proxy.py --avd YOUR_AVD --check-video-camera --camera-viewer
```

For a new phone, pass its own recording directly to the one-shot setup. This
runs the same configurator before the first boot and works for every selected
app, including POF:

```sh
./setup_galaxy_s25_avd.sh --pof-signup \
  --camera-video "/absolute/path/to/this-phone.mp4"
```

`--front-camera videofile:PATH` remains supported for compatibility. A selected
video is never replaced with the synthetic `emulated` camera based on the app.

For the selected `10f841ca` phone, double-click or run
`launch_s25_video_camera.command`. It uses the saved per-phone media/profile;
it no longer overrides both cameras with the shared raw recording. Re-running
the check on an already-running phone reuses that exact AVD instead of
starting a duplicate. Close it first to change its media or launch/proxy args.

`configure_video_camera.py` refuses to change a running AVD. It preserves an
original with a checksum under the AVD's private `camera/` directory, applies
the saved proportional crop, encodes all-intra VP9/WebM, and caches the result.
It saves these native settings, with backups of changed files:

```ini
# config.ini
hw.camera.front=environment
hw.camera.back=emulated

# environment.ini
version=1
scene.mode=videofile:/absolute/path/to/prepared.webm
background.enabled=false

# AVD.conf, within [perAvd]
virtualscene\tv_animation=true
```

The environment is **inside this emulator**, not a Mac camera or desktop
source. `background.enabled=false` keeps it out of the phone's background.
An environment/virtualscene rear camera would share the front movie, so this
profile uses a separate emulated rear placeholder. Keeping two camera entries
also avoids the stock Camera crashing on a previously saved front index.
Existing independent rear sources are preserved. No phone is recreated, no
app data is cleared, and identifiers are not regenerated.

The complete per-phone record is `camera/native-camera.json`; the original,
prepared media and media manifest remain private and out of Git. Normal new
phone setup with a `videofile:` front source now calls this configurator before
boot, rather than launching the unprepared recording directly.

### Preview and verification

`Camera Feed Preview` is our small on-device viewer. It requests the **normal
front Camera2 API**; it has no Internet permission and does not read or play
the host video file itself. The source is still the emulator's native front
camera provider. The viewer does not become the default camera application or
replace the provider. It releases the camera on pause so other apps can use it.
Its current validated viewport is portrait 3:4, matching this S25 profile.

The startup check compares Camera2 image-plane pixel samples, not an animated
counter, status bar, first-frame screenshot, or elapsed time alone. It requires
changing pixels in both halves of the observation, so “moves once then freezes”
does not pass. The supplied ~8.04 s clip is sampled for 22 s. Diagnostic logging
is bounded; the native video and preview continue afterward. The viewer is
built/signed once per source revision, with a stable local debug key reused
across phones and evidence directories. An unchanged installed build is reused.

Reports and first/latest frame samples go under
`.local/video-camera/AVD_NAME/direct/`; successful verification is recorded in
the per-phone profile as `verified_camera2_pixels`, **not** a claim that the
stock Camera preview or every third-party app is fixed. Software-rendered
emulator performance may limit frame rate. This checks moving camera data,
not real-phone authenticity or acceptance by another app.

For the stock Camera display check alone, use `verify_camera_playback.py` with
`--serial`, `--avd`, `--seconds` and `--output`. For direct API diagnosis, use
`camera_probe/build_and_run.py` with `--serial`, `--avd` and `--keep-preview`.
Use a longer `--seconds` (up to 600) for longer recordings. Inspect the reported
observed span; changing frames alone is not proof of every frame or loop order.

### Failed attempts to avoid repeating

On the second AVD, changing Qt window visibility, forcing GLES, toggling nodraw,
and all-intra H264 did not establish a moving stock preview. MJPEG/AVI was not
supported by this SDK build; MJPEG/MOV opened the container but the decoder was
unsupported. Those are **not** the saved defaults. Runtime inspection showed
the animation flag enabled and video time advancing. Direct Camera2 samples
then established actual changing source images despite the frozen stock view.
The saved compatibility path is VP9/WebM plus the native environment and our
Camera2 reader/viewer, not another experimental loop trampoline.

The earlier experimental camera patches in `10f841ca`'s private engines were
restored from their original per-phone backups, preserving the separate modem
identity changes. Preflight now detects the known abandoned trampolines and
refuses them; it never patches or re-signs an engine. Do not blindly replace a
private engine with the shared SDK binary or apply `patch_video_camera_loop.py`.

For implementation context, the Android emulator's [native scene clock](https://android.googlesource.com/platform/external/qemu/+/emu-main-dev/android/android-emu/android/ver/src/Scene.cpp)
and [camera frame path](https://android.googlesource.com/platform/external/qemu/+/emu-main-dev/android/android-emu/android/camera/camera-virtualscene-utils.cpp)
are upstream source; the runtime observations above were checked locally.

## Root cause of the frozen preview (24 October 2026, evening)

The frozen stock preview on the S25 phones is **not** caused by the media, the
framing, the VP9/H264 choice, the `environment` vs `videofile:` source, the
animation flag, the render mode, the system image, the CPU/RAM profile or the
private emulator engine. Each of those was ruled out on screen: the same
prepared WebM plays with full motion in the stock Camera front preview on a
throwaway android-35 AVD under emulator 37.2.12, with 4 cores and 4 GB, and
even when launched through the S25's private engine.

The cause is inside the S25 boot fixtures. `device_file_aliases.sh` renames
`/dev/goldfish_sync` to `/dev/s25_gpu_sync` and bind-mounts patched graphics
libraries, then bind-mounts the `renderer-egl` directory over
`/vendor/lib64/egl`. That directory mount hides the patched
`libEGL_emulation.so`, so the EGL library every app loads still opens
`/dev/goldfish_sync`, which no longer exists. EGL native fences then fail
(`EglManager::createReleaseFence: error dup'ing native fence fd` thousands of
times on the S25, zero on the throwaway), and every `SurfaceTexture` consumer
(stock Camera, CameraX `PreviewView`, the back `emulated` test pattern too)
shows one frame forever. A YUV `ImageReader` needs no fence, which is why the
old pixel check passed on a frozen phone.

**Workaround that leaves the boot scripts untouched:** launch with
`-feature -GLAsyncSwap`. The host then does not advertise native sync, guest
EGL never tries the sync device, and previews move. `emulator_proxy.py` adds
this automatically for any phone with S25 identifiers or a `videofile:` front
camera (`graphics_sync_options`). Verified on `10f841ca`: 24 distinct stock
Camera frames in 12 s and no fence errors. The per-phone QEMU profile
(`ro.kernel.qemu=0`) was tested live and is not involved.

Verification tooling: `camera_probe/build_and_run.py --mode texture` checks the
path real apps use; treat a passing `--mode yuv` alone as insufficient.
`configure_video_camera.py --fps 30` (default) now resamples the clip to the
emulated camera's 30 fps instead of repeating 24 fps frames.

## Swapping the clip on one phone

### Physical Mac camera performance (27 October 2026)

For the Tinder phone's physical FaceTime HD camera, `phone-bridge/run_mac_camera.py`
resolves the actual FaceTime device and launches through `emulator_proxy.py`
with `-camera-front webcam<N> -gpu host`. Do not substitute the enumerated
iPhone continuity device or OBS camera. Keep the browser bridge in
`EMU_LIVE_CAMERA=0` mode to prevent replacing that direct source.

This is separate from the saved video playback recipe. On this Apple M3 Mac,
automatic rendering selected swangle/SwiftShader and native camera delivery
to Tinder was measured at 11.27–16.09 fps. Reducing browser display encoding
to 960px/30fps yielded 14.71–16.46 fps. A two-second CPU sample confirmed
software graphics in the emulator. An isolated `-gpu host` run selected
Apple M3 / Metal, kept `-GLAsyncSwap`, and passed Camera2 SurfaceTexture motion
at 1280x960: 66 distinct samples over 13.293 seconds, 400 consumer updates.
Camera-service delivery counters measured 29.69–30.06 fps across three
three-second intervals. Report: `.local/live-camera/facetime-hostgpu-probe/`.
These are delivery/motion measurements, not proof of third-party biometric
acceptance or a reason to change every AVD's renderer. No emulator binary,
boot fixture or original media was modified for this test.

### Browser live camera (27 October 2026)

`phone-bridge/` can attach Safari's actual camera to a single AVD using native
`videofile:` without OBS or a system-wide camera. Do not revive the original
FIFO implementation: native `RawVideofileSource::Start` seeks, and its frame
reads can block QEMU. `native_video_camera.py` now refuses named pipes.

The replacement is a regular, fixed-size WebM file with independent VP9
frames and a half-second native timeline. Each received frame updates every
fixed-size cluster. The file stays seekable, so the normal native player can
seek/loop without waiting on network input. It lives in a private temporary
path without spaces: camera-service tokenization otherwise truncates a path
at `EMU Testing`. Existing saved camera profiles/media remain unchanged.

The bridge retains 3:4 crop-to-fill and the left-packed 640x480 canvas. Local
preview mirroring does not change the camera data. Acknowledgements follow
encoding and file update; Safari permits at most two frames in flight. Closing
Safari's camera leaves browser control and the emulator running, and clears
the native source to black. A source change requires one targeted restart;
reconnecting to the same source does not.

On `Galaxy_S25_20261027_tinder_f001699c`, a network diagnostic driving the
actual Camera2 SurfaceTexture passed with 271 consumer updates, 22 distinct
pixel samples, and 12.484 seconds observed. Report:
`.local/live-camera/network-seekable-probe-final/report.json`.
This establishes preview motion for that diagnostic, not end-to-end iPhone
latency or acceptance by a third-party verification app. Test actual Safari
capture separately after the user grants camera permission. Keep
`-feature -GLAsyncSwap` enabled via the normal launcher.

```sh
python3 swap_camera_video.py --status                                  # every phone's clip
python3 swap_camera_video.py --avd Galaxy_S25_20261024_10f841ca --video /path/new.mp4 --restart
```

`--restart` closes that one phone if it is running; without it a running phone
is refused and nothing changes. The clip is cropped to the saved 3:4 preview,
resampled to 30 fps, cached by checksum under the phone's private `camera/`
folder, and the phone is relaunched through `emulator_proxy.py` with the
on-screen camera check. Switching back to a clip used before is instant. Use
`--no-launch` to only save the clip, `--preview-size` for another app preview.
Other phones are never touched. The emulator reads the camera source at start,
so there is no hot swap on a running phone.

## Framing rule for every future video

**Match the actual app camera preview's aspect ratio, not the phone screen or
the source video's ratio. Scale proportionally to cover, then crop to fill.**
Do not squeeze/stretch, shrink-to-fit, or add bars inside the visible preview.
Recheck the preview when the app, orientation, stream size, or device changes.

The working Camera app preview is 1080×1440, portrait **3:4**. Its black screen
area outside the preview is app layout, not missing video. The source is
1080×1920, **9:16**, so filling this preview necessarily removes some top/bottom.

## Original verified H264 preparation (legacy first phone)

The original is saved privately as `camera/source.mp4` inside the AVD directory.
Its SHA-256 is recorded in `camera_profiles/s25-native.json`. Keep original
media out of Git. The working output is `camera/front-framed.mp4` there.

```sh
ffmpeg -v error -n -i "/absolute/path/original.mp4" -an \
  -vf 'scale=720:1280,crop=720:960:0:130,pad=1280:960:0:0:black,setsar=1' \
  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  -movflags +faststart "/absolute/path/front-framed.mp4"
```

This scales to 720×1280, crops a 720×960 portrait window at y=130, then packs
it at x=0 into a 1280×960 encoded canvas. The slightly high crop is intentional
face framing (130 pixels removed above, 190 below). The saved vertical anchor
is 130/320 = 0.40625; use 0.5 for a geometrically centered crop on new material.

The **left-packed canvas is a renderer-specific workaround**, verified on this
emulator. Its visible portrait region samples the left 720 pixels. Centering
the portrait within the encoded landscape canvas caused the earlier cut-off
or shrunken-looking feed. Do not confuse the encoded canvas ratio with the
visible preview ratio. Other renderer versions/devices need visual calibration.

For legacy proportional H264 preparation using the saved geometry:

```sh
python3 prepare_camera_video.py "/absolute/path/original.mp4" "/absolute/path/new-front.mp4"
```

For a different measured preview, pass `--preview-size WIDTHxHEIGHT` and,
optionally, `--vertical-anchor 0.5`. The helper does **not** detect the preview
automatically. It preserves its exact ratio and saves a JSON preparation
manifest alongside the output. It refuses to overwrite files. `--dry-run`
prints the plan without writing. The saved native packing calibration remains
in effect; verify other ratios visually before treating them as supported.

## Persistent emulator settings

This section records the **legacy direct-videofile path** on the first test
phone. Use the complete configurator above for the second phone/compatibility
workflow; do not mix its `environment` selection with this legacy front setting.

These are already saved on the working AVD. Leave the running phone alone
when merely referring to this recipe. To apply to another **closed** AVD,
preserve its other settings and set the following in its `config.ini`:

```ini
hw.camera.front=videofile:/absolute/path/to/that.avd/camera/front-framed.mp4
```

In `AVD.conf`, under the existing `[perAvd]` section, set this literal Qt key:

```ini
virtualscene\tv_animation=true
```

**Animation must be enabled.** With it disabled, native video froze on the
first frame. The native player repeats the clip; no binary patch is needed.
Do not apply the experimental `patch_video_camera_loop.py` for this recipe.
The back camera stays `virtualscene`.

After changing media/config, fully close and cold-start that same emulator;
an Android-only reboot is insufficient. Do not recreate the phone or wipe data.
For the saved test phone, retain its private engine/ramdisk launch workflow:

```sh
python3 emulator_proxy.py --avd Galaxy_S25_20261024_a9690b26 -port 5556
```

Use an available port if 5556 is occupied. Wait for boot and shared storage to
mount before opening Camera. Select the front camera. Verify proportional
framing and motion across at least two clip durations (this source is ~8 s).
The original setup was visually checked across repeated loops. Other apps
can request different stream/preview ratios; measure those before re-preparing.
