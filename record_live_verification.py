#!/usr/bin/env python3
"""Record the live Mac FaceTime HD Camera during Tinder selfie verification.

The emulator runs with `-camera-front webcam1` (direct Mac FaceTime HD Camera,
no OBS Virtual Camera in the middle). This script watches the emulator window:
1. As soon as Tinder's selfie oval screen appears (a few seconds before 'I'm ready'
   is clicked), starts recording the Mac camera in parallel to:
     /Users/rodion/orca/projects/EMU Testing/live_verification_<timestamp>.mp4
   (and the uncropped 1080p feed to `live_verification_<timestamp>_raw1080p.mp4`).
2. Once 'I'm ready' is clicked and the verification scan finishes (transitioning
   to 'Uploading encrypted 3d video scan'), stops recording and prints the saved
   video path.
"""

import argparse
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import live_face_track as track

ROOT = Path(__file__).resolve().parent


class FFmpegMP4Writer:
    """High-quality real-time H.264 MP4 writer using ffmpeg stdin pipe."""

    def __init__(self, output_path: Path, width: int, height: int, fps: float = 30.0):
        self.output_path = Path(output_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.proc = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{self.width}x{self.height}",
                "-r",
                f"{self.fps:.2f}",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "12",
                "-g",
                "1",
                "-pix_fmt",
                "yuv420p",
                str(self.output_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.frames_written = 0

    def write(self, bgr_frame: np.ndarray):
        if self.proc is not None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write(bgr_frame.tobytes())
                self.frames_written += 1
            except BrokenPipeError:
                pass

    def close(self):
        if self.proc is not None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None


class MacCameraRecorder:
    """Records Mac FaceTime HD Camera via shared OpenCV AVFoundation capture (no device lock)."""

    def __init__(self, camera_index: int = 1, width: int = 1080, height: int = 1440, fps: float = 30.0):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._portrait_writer: FFmpegMP4Writer | None = None
        self._raw_writer: FFmpegMP4Writer | None = None
        self.portrait_path: Path | None = None
        self.raw_path: Path | None = None
        self.recording = False
        self.ready_event = threading.Event()
        self.error: str | None = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="mac-cam-recorder", daemon=True)
        self._thread.start()
        self.ready_event.wait(timeout=8.0)
        if self.error:
            raise RuntimeError(self.error)

    def start_recording(self, portrait_path: Path, raw_path: Path, raw_w: int = 1920, raw_h: int = 1080):
        with self._lock:
            if self.recording:
                return
            self.portrait_path = Path(portrait_path)
            self.raw_path = Path(raw_path)
            self._portrait_writer = FFmpegMP4Writer(self.portrait_path, self.width, self.height, self.fps)
            self._raw_writer = FFmpegMP4Writer(self.raw_path, raw_w, raw_h, self.fps)
            self.recording = True

    def stop_recording(self):
        with self._lock:
            self.recording = False
            pw, rw = self._portrait_writer, self._raw_writer
            self._portrait_writer = None
            self._raw_writer = None
        if pw is not None:
            pw.close()
        if rw is not None:
            rw.close()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self.stop_recording()

    def _crop_portrait(self, frame: np.ndarray) -> np.ndarray:
        sh, sw = frame.shape[:2]
        target_ratio = self.width / self.height  # 3:4 = 0.75
        if sw / sh > target_ratio:
            crop_h = sh
            crop_w = int(round(sh * target_ratio))
        else:
            crop_w = sw
            crop_h = int(round(sw / target_ratio))
        x0 = (sw - crop_w) // 2
        y0 = (sh - crop_h) // 2
        crop = frame[y0 : y0 + crop_h, x0 : x0 + crop_w]
        return cv2.resize(crop, (self.width, self.height), interpolation=cv2.INTER_LANCZOS4)

    def _run(self):
        # Do NOT call cap.set(...) so AVFoundation does not lock the device for configuration,
        # allowing the Android Emulator (-camera-front webcam1) and this recorder to share
        # the Mac's FaceTime HD Camera simultaneously.
        cap = cv2.VideoCapture(self.camera_index)
        ok, first = cap.read()
        if not ok or first is None:
            self.error = f"Could not read from Mac camera index {self.camera_index}"
            self.ready_event.set()
            cap.release()
            return

        self.ready_event.set()
        period = 1.0 / max(10.0, self.fps)
        try:
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.01)
                    continue
                with self._lock:
                    if self.recording:
                        if self._portrait_writer is not None:
                            portrait = self._crop_portrait(frame)
                            self._portrait_writer.write(portrait)
                        if self._raw_writer is not None:
                            if frame.shape[1] != self._raw_writer.width or frame.shape[0] != self._raw_writer.height:
                                raw_f = cv2.resize(frame, (self._raw_writer.width, self._raw_writer.height))
                            else:
                                raw_f = frame
                            self._raw_writer.write(raw_f)
                elapsed = time.monotonic() - t0
                if period - elapsed > 0:
                    time.sleep(period - elapsed)
        finally:
            cap.release()


def detect_camera_opencv_index(camera_name: str = "Rodion’s iPhone Camera") -> int:
    """Match OpenCV VideoCapture index to the named AVFoundation camera."""
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "avfoundation",
                "-framerate",
                "30",
                "-video_size",
                "1920x1080",
                "-i",
                camera_name,
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "pipe:1",
            ],
            capture_output=True,
            timeout=5,
        )
        if len(res.stdout) == 1920 * 1080 * 3:
            ref = np.frombuffer(res.stdout, dtype=np.uint8).reshape((1080, 1920, 3))
            ref_mean = float(ref.mean())
            best_idx = 0
            best_diff = 1e9
            for idx in range(4):
                cap = cv2.VideoCapture(idx)
                ok, frame = cap.read()
                cap.release()
                if ok and frame is not None:
                    diff = abs(float(frame.mean()) - ref_mean)
                    if diff < best_diff:
                        best_diff = diff
                        best_idx = idx
            return best_idx
    except Exception:
        pass
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--avd", help="defaults to the AVD running on --serial")
    parser.add_argument("--camera-index", type=int, default=None, help="OpenCV camera index")
    parser.add_argument(
        "--camera-name",
        default="Rodion’s iPhone Camera",
        help="AVFoundation camera name (e.g. 'Rodion’s iPhone Camera' or 'FaceTime HD Camera')",
    )
    parser.add_argument(
        "--auto-tap-ready",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically tap 'I'm ready' ~3 seconds after recording starts and face is inside oval",
    )
    parser.add_argument(
        "--pre-ready-delay",
        type=float,
        default=3.5,
        help="Seconds to record on the oval screen before auto-tapping 'I'm ready'",
    )
    parser.add_argument("--output", type=Path, help="Optional explicit output .mp4 path in project")
    args = parser.parse_args(argv)

    avd = args.avd or track.avd_name(args.serial)
    model = ROOT / "models" / "blaze_face_short_range.tflite"
    detector = track.make_detector(model, 0.40)
    capture = track.EmulatorWindowCapture(avd, serial=args.serial)

    cam_idx = args.camera_index if args.camera_index is not None else detect_camera_opencv_index(args.camera_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    portrait_out = args.output or (ROOT / f"live_verification_iphone_{timestamp}.mp4")
    raw_out = portrait_out.with_name(f"{portrait_out.stem}_raw1080p.mp4")

    recorder = MacCameraRecorder(camera_index=cam_idx, width=1080, height=1440, fps=30.0)
    recorder.start()
    print(
        f"Connected to {args.camera_name!r} (OpenCV index={cam_idx}) in shared mode.",
        flush=True,
    )
    print(
        f"Watching emulator window ({avd} on {args.serial}) for Tinder selfie oval ...",
        flush=True,
    )

    recording_started_at: float | None = None
    ready_tapped = False
    entered_active_scan = False
    post_scan_no_oval_count = 0
    active_scan_frames = 0
    last_retry_tap = 0.0

    try:
        while True:
            image = capture.capture()
            if image is None:
                time.sleep(0.2)
                continue

            ih, iw = image.shape[:2]
            oval, banner_instruction = track.detect_oval_and_banner(image)
            measurement = track.measure_alignment(image, detector)

            if oval is not None:
                post_scan_no_oval_count = 0
                _ox, _oy, _ow, oh, _ang = oval

                # 1. Start recording as soon as we reach the oval screen!
                if not recorder.recording:
                    recorder.start_recording(portrait_out, raw_out)
                    recording_started_at = time.monotonic()
                    print(
                        f"\n[RECORDING STARTED] Oval detected! Saving live Mac camera to:\n"
                        f"  -> {portrait_out}\n"
                        f"  -> {raw_out}",
                        flush=True,
                    )

                elapsed_rec = time.monotonic() - (recording_started_at or time.monotonic())

                # 2. Check if we are in the active verification scan (after 'I'm ready')
                is_large_oval = oh >= ih * 0.44
                has_active_banner = banner_instruction in (
                    "move_closer",
                    "move_away",
                    "hold_steady",
                    "head_straight",
                )
                if is_large_oval or has_active_banner or ready_tapped:
                    active_scan_frames += 1
                    if active_scan_frames >= 3:
                        entered_active_scan = True

                # 3. Optionally tap "I'm ready" a few seconds after recording starts once enabled
                if (
                    args.auto_tap_ready
                    and not ready_tapped
                    and measurement is not None
                    and measurement.get("ready_button_enabled")
                    and elapsed_rec >= args.pre_ready_delay
                ):
                    ready_tapped = True
                    print(
                        f"[AUTO-TAP] Recorded {elapsed_rec:.1f}s on pre-ready oval; tapping 'I'm ready' now! "
                        f"Complete the verification using your Mac camera ...",
                        flush=True,
                    )
                    track.tap_device_ready(args.serial, measurement)

                instr_label = (
                    measurement["instruction"]
                    if measurement is not None
                    else (banner_instruction or ("active_oval" if is_large_oval else "pre_ready_oval"))
                )
                print(
                    f"rec={elapsed_rec:5.1f}s state={instr_label} "
                    f"active_scan={entered_active_scan} face_detected={measurement is not None}",
                    flush=True,
                )
            else:
                if not recorder.recording and (time.monotonic() - last_retry_tap) > 4.0:
                    if track.detect_failure_screen(image, detector):
                        print("On Tinder retry screen; tapping 'Try again' to open the oval ...", flush=True)
                        track.tap_device_try_again(args.serial)
                        last_retry_tap = time.monotonic()
                        time.sleep(1.0)
                        continue

                if recorder.recording and entered_active_scan and active_scan_frames >= 8:
                    post_scan_no_oval_count += 1
                    print(
                        f"Oval completed ({post_scan_no_oval_count}/5) — transitioning to encrypted upload ...",
                        flush=True,
                    )
                    if post_scan_no_oval_count >= 5:
                        recorder.stop_recording()
                        print(
                            f"\n[RECORDING COMPLETE] Verification scan finished (sending encrypted video)!\n"
                            f"Saved 3:4 phone camera video : {portrait_out}\n"
                            f"Saved raw 1080p Mac video    : {raw_out}",
                            flush=True,
                        )
                        break

            time.sleep(0.20)
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    finally:
        recorder.stop()
        detector.close()
        if portrait_out.is_file():
            print(f"Saved recording path: {portrait_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
