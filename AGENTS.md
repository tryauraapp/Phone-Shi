# Camera-feed work

Before changing video-camera preparation or emulator camera configuration, read
`VIDEO_CAMERA.md` and the saved `camera_profiles/s25-native.json` profile.

- Match the **actual app camera preview aspect ratio**, not the phone display
  or source video. Scale proportionally and crop to fill; do not stretch or
  shrink-to-fit unless the user explicitly asks for that.
- The saved S25 preview is portrait 3:4. Other apps/devices/orientations may
  differ: measure their preview and pass that size to `prepare_camera_video.py`.
  The helper does not automatically discover preview dimensions.
- Preserve the documented native renderer packing workaround and enabled
  animation setting. Do not assume this calibration works on every renderer.
- Keep playback emulator-scoped using native `videofile:`; no OBS or Mac-wide
  virtual camera is needed. Do not apply the experimental binary loop patch.
- Preserve original private media, existing AVD data and unrelated running
  phones. Do not restart a working phone merely to document its setup.
- Use `configure_video_camera.py` on a closed AVD for the complete compatibility
  profile, not just an ad hoc copy of the legacy H264 command. It keeps the
  original, prepares crop-to-fill VP9/WebM, and persists native environment,
  animation and preview preferences. Normal new-phone video setup calls it.
- A saved flag, first-frame image, or elapsed time is not proof of playback.
  Test changing front Camera2 ImageReader pixels with the saved probe. On
  `10f841ca`, the stock Camera preview froze even while real camera frames
  changed. The saved launcher uses Camera Feed Preview, a real Camera2 viewer;
  it is not a video-file player and does not replace the camera provider.
- Do not claim the stock Camera preview bug or every third-party app is fixed.
  Do not make failed attempts (GLES forcing, nodraw toggles, MJPEG, or the old
  cadence patches) defaults. Read the recorded diagnostics in VIDEO_CAMERA.md.
- `emulator_proxy.py` adds `-feature -GLAsyncSwap` for lab phones and video
  cameras. The S25 boot fixture hides the patched EGL library, so guest native
  fences fail and every SurfaceTexture preview freezes after one frame without
  it. Keep that flag; do not change the boot scripts to fix the camera.
- Verify camera motion with `camera_probe/build_and_run.py --mode texture`
  or by watching the stock Camera on screen. A passing YUV ImageReader check
  alone proves nothing about app previews.
