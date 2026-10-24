#!/usr/bin/env python3
"""
Stream a video file continuously as a live virtual camera feed on macOS.
Bypasses the OBS application while delivering exact framerate, full quality,
and native aspect ratio to Android Studio emulators.

Requirements:
    pip install pyvirtualcam numpy
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def probe_video(video_path: Path):
    """Inspect video dimensions and frame rate using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate",
        "-of", "json",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])

    fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1"
    num, den = map(int, fps_str.split("/"))
    fps = (num / den) if den != 0 else 30.0

    return width, height, fps


def stream_video(video_path: Path, rotate: int = 0, camera_fps: float = None):
    try:
        import numpy as np
        import pyvirtualcam
    except ImportError:
        print("\n[!] Missing dependencies. Please run:", file=sys.stderr)
        print("    pip install pyvirtualcam numpy\n", file=sys.stderr)
        sys.exit(1)

    width, height, fps = probe_video(video_path)
    fps = camera_fps or fps

    # Adjust output dimensions if rotating 90 or 270 degrees
    out_w, out_h = (height, width) if rotate in (90, 270) else (width, height)

    print("=" * 60)
    print(f" Source Video: {video_path}")
    print(f" Source Size:  {width}x{height} @ {fps:.2f} FPS")
    if rotate:
        print(f" Rotation:     {rotate}° (Virtual Cam Output: {out_w}x{out_h})")
    print("=" * 60)

    # Build ffmpeg decoding pipeline
    vf_filters = []
    if rotate == 90:
        vf_filters.append("transpose=1")
    elif rotate == 180:
        vf_filters.append("transpose=2,transpose=2")
    elif rotate == 270:
        vf_filters.append("transpose=2")

    filter_arg = ["-vf", ",".join(vf_filters)] if vf_filters else []

    ffmpeg_cmd = [
        "ffmpeg",
        "-re",                          # Read input at native frame rate
        "-stream_loop", "-1",            # Loop input video indefinitely
        "-i", str(video_path),
        *filter_arg,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",            # Raw BGR frame stream
        "-"
    ]

    print(f"Starting virtual camera with device resolution {out_w}x{out_h} @ {fps:.1f} FPS...")
    frame_size = out_w * out_h * 3

    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    try:
        with pyvirtualcam.Camera(width=out_w, height=out_h, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
            print(f"Virtual camera active ({cam.device}). Streaming live feed...")
            print("Press Ctrl+C to stop.\n")
            while True:
                raw_frame = proc.stdout.read(frame_size)
                if len(raw_frame) != frame_size:
                    break
                frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((out_h, out_w, 3))
                cam.send(frame)
                cam.sleep_until_next_frame()
    except KeyboardInterrupt:
        print("\nStreaming stopped.")
    finally:
        proc.terminate()
        proc.wait()


def main():
    default_video = Path(__file__).resolve().parent / "bumble-signup/camera/phone-video.mp4"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?", type=Path, default=default_video,
                        help=f"Path to the video file to stream (default: {default_video})")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0,
                        help="Rotate feed clockwise (useful if Android phone displays webcam sideways)")
    parser.add_argument("--fps", type=float, help="Override playback frame rate")

    args = parser.parse_args()

    if not args.video.is_file():
        parser.error(f"Video file not found: {args.video}")

    stream_video(args.video.resolve(), rotate=args.rotate, camera_fps=args.fps)


if __name__ == "__main__":
    main()
