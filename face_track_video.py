#!/usr/bin/env python3
"""Center a face in video frames for app oval/selfie verification.

Reads the source video, detects the face per frame with MediaPipe, and
outputs a cropped/zoomed video where the face sits at a configurable
target position and size.  The result is fed to the existing camera
preparation pipeline (prepare_camera_video.py / swap_camera_video.py).

    # Basic: center face for Tinder oval, then swap onto a phone
    python3 face_track_video.py selfie.mp4 selfie-tracked.mp4

    # Preview detection without encoding (prints face stats per frame)
    python3 face_track_video.py selfie.mp4 --preview

    # Custom target position and face size
    python3 face_track_video.py selfie.mp4 out.mp4 \\
        --target-x 0.5 --target-y 0.38 --face-fill 0.45

    # Then feed to existing camera swap
    python3 swap_camera_video.py --avd YOUR_AVD --video out.mp4 --restart
"""

import argparse
import json
import math
import sys
from pathlib import Path

try:
    import cv2
except ImportError:
    sys.exit("opencv-python-headless is required.\n  .venv/bin/pip install opencv-python-headless mediapipe")
try:
    import mediapipe as mp
except ImportError:
    sys.exit("mediapipe is required.\n  .venv/bin/pip install mediapipe")
import numpy as np


def smooth(prev, curr, alpha):
    if prev is None:
        return curr
    return prev + alpha * (curr - prev)


def detect_faces_pass(cap, detector, total_frames):
    """First pass: detect face in every frame, return list of (cx, cy, w, h) or None."""
    detections = []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)
        if result.detections:
            best = max(result.detections, key=lambda d: d.categories[0].score)
            bb = best.bounding_box
            cx = (bb.origin_x + bb.width / 2) / frame.shape[1]
            cy = (bb.origin_y + bb.height / 2) / frame.shape[0]
            w = bb.width / frame.shape[1]
            h = bb.height / frame.shape[0]
            detections.append((cx, cy, w, h))
        else:
            detections.append(None)
        frame_idx += 1
        if frame_idx % 30 == 0:
            pct = frame_idx * 100 // max(total_frames, 1)
            print(f"\r  detecting faces: {pct}% ({frame_idx}/{total_frames})", end="", flush=True)
    print(f"\r  detecting faces: done ({frame_idx} frames)          ")
    return detections


def fill_gaps(detections):
    """Interpolate over frames where no face was found."""
    n = len(detections)
    if not n:
        return detections
    filled = list(detections)
    last_good = None
    for i in range(n):
        if filled[i] is not None:
            if last_good is not None and i - last_good > 1:
                a = filled[last_good]
                b = filled[i]
                for j in range(last_good + 1, i):
                    t = (j - last_good) / (i - last_good)
                    filled[j] = tuple(a[k] + t * (b[k] - a[k]) for k in range(4))
            last_good = i
    if last_good is not None:
        for i in range(last_good + 1, n):
            filled[i] = filled[last_good]
        for i in range(0, n):
            if filled[i] is None:
                filled[i] = filled[last_good]
            else:
                break
        first_good = next(j for j in range(n) if detections[j] is not None)
        for i in range(0, first_good):
            filled[i] = filled[first_good]
    return filled


def smooth_trajectory(detections, alpha):
    """Apply exponential smoothing to the face trajectory."""
    smoothed = []
    prev = None
    for d in detections:
        if d is None:
            smoothed.append(prev)
            continue
        cx, cy, w, h = d
        if prev is None:
            s = (cx, cy, w, h)
        else:
            s = (
                smooth(prev[0], cx, alpha),
                smooth(prev[1], cy, alpha),
                smooth(prev[2], w, alpha),
                smooth(prev[3], h, alpha),
            )
        smoothed.append(s)
        prev = s
    return smoothed


def compute_crop(face_cx, face_cy, face_w, target_x, target_y, face_fill,
                 src_w, src_h, out_w, out_h):
    """Compute a crop rectangle that places the face at the target position.

    face_fill is how much of the OUTPUT width the face should occupy. The crop
    zooms in (or out) so the face ends up at that size, then positions the crop
    so the face center lands at (target_x, target_y) within the output.

    Returns (crop_x, crop_y, crop_w, crop_h) in source pixel coordinates.
    """
    out_aspect = out_w / out_h
    face_px = face_w * src_w
    # How wide the crop must be so that face_px / crop_w == face_fill.
    crop_w = face_px / max(face_fill, 0.01)
    crop_h = crop_w / out_aspect
    # If crop exceeds source, fit the limiting axis and accept a larger face.
    if crop_w > src_w or crop_h > src_h:
        scale = max(crop_w / src_w, crop_h / src_h)
        crop_w /= scale
        crop_h /= scale
    crop_w = max(4, crop_w)
    crop_h = max(4, crop_h)
    # Position the crop so the face center sits at (target_x, target_y).
    cx_px = face_cx * src_w
    cy_px = face_cy * src_h
    crop_x = cx_px - target_x * crop_w
    crop_y = cy_px - target_y * crop_h
    crop_x = max(0, min(crop_x, src_w - crop_w))
    crop_y = max(0, min(crop_y, src_h - crop_h))
    return int(round(crop_x)), int(round(crop_y)), int(round(crop_w)), int(round(crop_h))


def render_pass(cap, trajectory, target_x, target_y, face_fill,
                out_w, out_h, writer, total_frames):
    """Second pass: crop each frame according to the smoothed trajectory."""
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        det = trajectory[frame_idx] if frame_idx < len(trajectory) else trajectory[-1]
        if det is None:
            crop_x, crop_y = 0, 0
            crop_w, crop_h = src_w, int(src_w * out_h / out_w)
        else:
            face_cx, face_cy, face_w, face_h = det
            crop_x, crop_y, crop_w, crop_h = compute_crop(
                face_cx, face_cy, face_w,
                target_x, target_y, face_fill,
                src_w, src_h, out_w, out_h)
        cropped = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
        resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        writer.write(resized)
        frame_idx += 1
        if frame_idx % 30 == 0:
            pct = frame_idx * 100 // max(total_frames, 1)
            print(f"\r  rendering: {pct}% ({frame_idx}/{total_frames})", end="", flush=True)
    print(f"\r  rendering: done ({frame_idx} frames)          ")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path, help="source video file")
    parser.add_argument("output", type=Path, nargs="?",
                        help="output video (omit with --preview)")
    parser.add_argument("--target-x", type=float, default=0.5,
                        help="horizontal face position in output (0=left, 0.5=center, 1=right)")
    parser.add_argument("--target-y", type=float, default=0.38,
                        help="vertical face position in output (0=top, 0.5=center, 1=bottom); "
                             "0.38 matches a typical app selfie oval")
    parser.add_argument("--face-fill", type=float, default=0.55,
                        help="how much of the output width the face should fill (0-1); "
                             "must be larger than the face's natural size to enable panning")
    parser.add_argument("--smooth", type=float, default=0.15,
                        help="tracking smoothness (0=frozen, 1=instant); lower is smoother")
    parser.add_argument("--output-size", default=None,
                        help="WxH output resolution (default: same as source)")
    parser.add_argument("--confidence", type=float, default=0.5,
                        help="minimum face detection confidence (0-1)")
    parser.add_argument("--hflip", action="store_true",
                        help="horizontally flip the output; use when the camera mirrors the image")
    parser.add_argument("--preview", action="store_true",
                        help="detect only; print face stats, no output video")
    parser.add_argument("--codec", default="mp4v",
                        help="FourCC codec for OpenCV writer (default mp4v)")
    args = parser.parse_args()

    if not args.preview and args.output is None:
        parser.error("output path required (or use --preview)")

    source = args.video.expanduser().resolve()
    if not source.is_file():
        parser.error(f"source not found: {source}")

    if args.output:
        output = args.output.expanduser().resolve()
        if output.exists():
            parser.error(f"output already exists: {output}")

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        parser.error(f"cannot open video: {source}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Source: {src_w}x{src_h} @ {fps:.1f} fps, ~{total_frames} frames")

    if args.output_size:
        out_w, out_h = map(int, args.output_size.lower().split("x"))
    else:
        out_w, out_h = src_w, src_h

    BaseOptions = mp.tasks.BaseOptions
    FaceDetector = mp.tasks.vision.FaceDetector
    FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    model_path = Path(__file__).resolve().parent / "models" / "blaze_face_short_range.tflite"
    if not model_path.is_file():
        parser.error(
            f"face detection model not found at {model_path}\n"
            "Download it:\n  curl -sL -o models/blaze_face_short_range.tflite "
            '"https://storage.googleapis.com/mediapipe-models/face_detector/'
            'blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"'
        )
    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=VisionRunningMode.IMAGE,
        min_detection_confidence=args.confidence,
    )

    print("Pass 1: detecting faces ...")
    detector = FaceDetector.create_from_options(options)
    detections = detect_faces_pass(cap, detector, total_frames)
    detector.close()

    detected_count = sum(1 for d in detections if d is not None)
    print(f"  faces detected in {detected_count}/{len(detections)} frames "
          f"({detected_count * 100 // max(len(detections), 1)}%)")

    if detected_count == 0:
        print("No faces detected in any frame. Cannot track.", file=sys.stderr)
        return 1

    if args.preview:
        for i, d in enumerate(detections):
            if d:
                cx, cy, w, h = d
                print(f"  frame {i:4d}: face at ({cx:.3f}, {cy:.3f}) size {w:.3f}x{h:.3f}")
        return 0

    filled = fill_gaps(detections)
    trajectory = smooth_trajectory(filled, args.smooth)

    print(f"Pass 2: rendering {out_w}x{out_h} ...")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    output.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*args.codec)
    writer = cv2.VideoWriter(str(output), fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        print(f"Cannot open writer for {output}", file=sys.stderr)
        return 1

    render_pass(cap, trajectory, args.target_x, args.target_y, args.face_fill,
                out_w, out_h, writer, total_frames)

    writer.release()
    cap.release()

    manifest = {
        "source": str(source),
        "output": str(output),
        "source_size": [src_w, src_h],
        "output_size": [out_w, out_h],
        "fps": fps,
        "total_frames": len(detections),
        "faces_detected": detected_count,
        "target_position": [args.target_x, args.target_y],
        "face_fill": args.face_fill,
        "smooth": args.smooth,
    }
    manifest_path = output.with_suffix(output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nDone: {output}")
    print(f"Manifest: {manifest_path}")
    print(f"\nNext: feed this to the camera pipeline:")
    print(f"  python3 swap_camera_video.py --avd YOUR_AVD --video {output} --restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
