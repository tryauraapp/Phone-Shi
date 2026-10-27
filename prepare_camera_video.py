#!/usr/bin/env python3
"""Prepare crop-to-fill media; never reconfigure or restart a running phone."""

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess


DEFAULT_PROFILE = Path(__file__).with_name("camera_profiles") / "s25-native.json"


def size(value):
    try:
        width, height = map(int, value.lower().split("x"))
        if min(width, height) < 2:
            raise ValueError()
        return width, height
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected positive WIDTHxHEIGHT") from exc


def framing_filter(preview, canvas, anchor):
    """Fill the visible area without stretching, then pack for native playback.

    This left-packed canvas is calibrated for the saved emulator renderer, not
    a universal camera format. A different renderer needs its own calibration.
    """
    pw, ph = preview
    cw, ch = canvas
    if min(pw, ph, cw, ch) < 2 or cw % 2 or ch % 2:
        raise ValueError("sizes must be positive; canvas dimensions must be even")
    if not math.isfinite(anchor) or not 0 <= anchor <= 1:
        raise ValueError("vertical anchor must be between 0 and 1")
    # Largest exact-ratio, even-sized rectangle inside the encoded canvas.
    ratio = Fraction(pw, ph)
    factor = min(cw // (2 * ratio.numerator), ch // (2 * ratio.denominator))
    if not factor:
        raise ValueError("preview ratio cannot fit this canvas exactly; use a larger canvas")
    width, height = 2 * factor * ratio.numerator, 2 * factor * ratio.denominator
    # Preserve source proportions while covering the visible rectangle.
    # The verified 1080x1920 source becomes 720x1280, cropped at y=130.
    filters = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:"
        "force_divisible_by=2,setsar=1,"
        f"crop={width}:{height}:trunc((iw-ow)/4)*2:"
        f"trunc((ih-oh)*{anchor}/2)*2,"
        f"pad={cw}:{ch}:0:0:black,setsar=1"
    )
    return filters, (width, height)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--preview-size", type=size,
                        help="actual app camera preview WIDTHxHEIGHT, not screen size")
    parser.add_argument("--vertical-anchor", type=float,
                        help="0=top, 0.5=center, 1=bottom; defaults to saved framing")
    parser.add_argument("--fps", type=float,
                        help="resample to the phone camera's frame rate (e.g. 30); default keeps the source rate")
    parser.add_argument("--hflip", action="store_true",
                        help="horizontally mirror the source video before framing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument('--codec', choices=['h264', 'vp9'], default='h264',
                        help='vp9/WebM is used by the native environment compatibility profile')
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    if profile["packing"] != "left" or profile["fit"] != "cover":
        parser.error("this helper supports only the calibrated left-packed cover profile")
    preview = args.preview_size or profile["preview_size"]
    anchor = (args.vertical_anchor if args.vertical_anchor is not None
              else profile["vertical_anchor"])
    try:
        filters, visible = framing_filter(preview, profile["canvas_size"], anchor)
    except ValueError as exc:
        parser.error(str(exc))
    if args.fps is not None:
        if not math.isfinite(args.fps) or not 1 <= args.fps <= 120:
            parser.error("--fps must be between 1 and 120")
        # Resample before framing so the camera HAL receives frames at its own rate
        # instead of repeating 24 fps source frames unevenly at 30 fps.
        filters = f"fps={args.fps:g}," + filters
    if args.hflip:
        filters = "hflip," + filters
    source, output = args.video.expanduser().resolve(), args.output.expanduser().resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {source}")
    manifest = output.with_suffix(output.suffix + ".json")
    if output.exists() or manifest.exists() or source == output:
        parser.error("output or its manifest already exists; choose a new filename")
    if args.codec == 'vp9':
        if output.suffix.lower() != '.webm':
            parser.error('VP9 compatibility media must use a .webm output filename')
        encoding = ['-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8',
                    '-g', '1', '-crf', '24', '-b:v', '0', '-pix_fmt', 'yuv420p']
    else:
        encoding = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    command = ["ffmpeg", "-v", "error", "-n", "-i", str(source), "-an", "-vf", filters,
               *encoding, str(output)]
    record = {"profile": str(args.profile.resolve()), "source": str(source),
              "preview_size": list(preview), "visible_size": list(visible),
              "canvas_size": profile["canvas_size"], "vertical_anchor": anchor,
              "fps": args.fps, "filter": filters, "codec": args.codec, "command": command}
    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True)
        with source.open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        record["source_sha256"] = digest.hexdigest()
        with manifest.open("x") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
