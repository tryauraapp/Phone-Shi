# iPhone to emulator camera bridge

Browser control starts by default and attaches to the already running emulator
without restarting it. Camera permission is not needed for phone control.

Safari captures the iPhone front camera, sends a 3:4 crop over a local TLS
WebSocket, and the Mac encodes independent VP9 frames into a bounded, seekable
WebM file consumed by the emulator's native `videofile:` camera provider.
Each update replaces every slot with the newest frame; there is no growing
recording or queue of stale camera frames. The native player loops its normal
half-second timeline. This does not use Continuity Camera, OBS, a system-wide
virtual camera, or binary emulator patches.

The old named-pipe implementation is removed: native camera startup seeks and
playback reads synchronously, so a live FIFO could stall the QEMU main loop.
Preflight now rejects named pipes. Live paths must not contain spaces because
the native camera service parses camera names as space-delimited tokens.

```sh
cd phone-bridge
npm install
chmod +x prepare_tls.sh
./prepare_tls.sh 192.168.10.23
BRIDGE_CA="$(mkcert -CAROOT)/rootCA.pem" npm start
```

Scan the printed QR. Install and trust the local CA once, open the secure link,
then tap **Allow camera**. When first applying the source the selected AVD is
restarted without wiping its data. Reconnecting to the same running source
does not restart it. Phone control stays available when Safari disconnects its
camera. Local preview mirroring does not mirror the data sent to Android.

Use `EMU_LIVE_CAMERA=0 npm start` for controller-only mode. Keep `BRIDGE_TOKEN`
stable across restarts to retain an existing QR. The emulator process is
independent of the web server and its logs go to `.local/live-camera/`.

For the physical Mac camera, enumerate devices with `emulator -webcam-list`.
On this Mac the FaceTime HD Camera was `webcam1` (the iPhone continuity device
was `webcam0`; do not substitute it). Close only the selected AVD and launch:

```sh
python3 phone-bridge/run_mac_camera.py
# To apply the options when this particular phone is already running:
python3 phone-bridge/run_mac_camera.py --restart
```

Run the bridge with `EMU_LIVE_CAMERA=0` in this mode. The native emulator reads
the physical camera; no Safari/JPEG/VP9/file adapter participates. Android
still receives an emulated Camera2 device with pixel-format conversion, not
the Mac's hardware identity or an iPhone sensor. Camera motion is separate
from acceptance by a third-party biometric verification system.

The helper resolves the physical camera by its name on each launch, since
`webcam<N>` numbering can change. It uses `-gpu host` for this direct-camera
profile: software rendering on this Mac limited delivered camera frames to
roughly 11–16 fps, while host-GPU capture counters measured approximately
30 fps. It still goes through `emulator_proxy.py` and retains `-GLAsyncSwap`.
This is a scoped, measured direct-camera configuration; global GPU defaults
and saved prerecorded-video profiles are not changed.

The browser display defaults to a 960-pixel longest edge at up to 30 fps and
4 Mbps. This controls scrcpy screen encoding only, not the incoming physical
camera. The previous 1280/60fps display could consume a guest CPU core in
`media.swcodec`, competing with the app's camera processing. Override through
`EMU_DISPLAY_FPS`, `EMU_DISPLAY_SIZE`, and `EMU_DISPLAY_BIT_RATE` if needed.

Validation: `node --test live-webm.test.mjs` checks concurrent updates against
a looping FFmpeg decoder. `check-camera-bridge.mjs` provides a diagnostic test
pattern over the WebSocket; use it only with CameraProbe/Camera Feed Preview.
Actual app-preview motion must be checked using the Camera2 texture probe,
not merely the received-frame count shown in the browser. Browser FPS counts
frames encoded/written by the server, not verified Android display updates.
