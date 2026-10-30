#!/usr/bin/env python3
"""Headless bridge between a VDS phone and the Phone Shi CRM.

Reuses the repo's gRPC/WebRTC viewer (vds_phone_view) without a window:
frames go to stdout as raw RGB, input comes from stdin as JSON lines.

stdout messages: b"PSF1" + u32 header length + JSON header + payload.
  {"type":"info","avd":...,"deviceWidth":W,"deviceHeight":H,"mode":"webrtc"}
  {"type":"state","state":"connected"}            (WebRTC connection state)
  {"type":"frame","w":W,"h":H,"format":"rgb24"}   payload = W*H*3 bytes
  {"type":"error","message":"..."}
stdin lines:
  {"type":"touch","x":123,"y":456,"down":true}    device pixels
  {"type":"key","key":"GoBack"}                   emulator key name
  {"type":"text","text":"hello"}
  {"type":"refresh"}                              repaint from a PNG screenshot
"""
from __future__ import annotations

import argparse
import io
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vds_phone_view"))

import endpoint as ep  # noqa: E402

RUNTIME_ROOTS = ["/opt/android-vm/run", "/var/lib/phone-shi/.android/run", "/run/user/0", "/root/.android"]
LIST_RUNNING = r'''
for d in {roots}; do
  for f in "$d"/avd/running/pid_*.ini; do
    [ -f "$f" ] || continue
    p="${{f##*pid_}}"; p="${{p%.ini}}"
    kill -0 "$p" 2>/dev/null || continue
    echo "== $f"; cat "$f"
  done
done
'''

out_lock = threading.Lock()


def emit(header, payload=b""):
    body = json.dumps(header).encode()
    with out_lock:
        sys.stdout.buffer.write(b"PSF1" + struct.pack(">I", len(body)) + body + payload)
        sys.stdout.buffer.flush()


def discover(host, key, user, serial):
    script = LIST_RUNNING.format(roots=" ".join(RUNTIME_ROOTS))
    result = subprocess.run(ep.ssh_base(host, key, user) + ["bash", "-s"], input=script,
                            capture_output=True, text=True, timeout=60, check=True)
    port = serial.split("-", 1)[1] if serial.startswith("emulator-") else serial
    for endpoint in ep.parse_discovery(result.stdout):
        if endpoint.get("port.serial") == port:
            return endpoint
    raise LookupError(f"{serial} is not running with a gRPC endpoint on {host}")


def frame_bytes(image):
    """Raw RGB bytes and size from an aiortc VideoFrame or a PNG screenshot message."""
    if hasattr(image, "to_ndarray"):
        array = image.to_ndarray(format="rgb24")
        return array.shape[1], array.shape[0], array.tobytes()
    from PIL import Image
    with Image.open(io.BytesIO(image.image)) as png:
        rgb = png.convert("RGB")
        return rgb.width, rgb.height, rgb.tobytes()


def input_loop(phone):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            kind = message.get("type")
            if kind == "touch":
                phone.touch(message["x"], message["y"], bool(message.get("down")),
                            int(message.get("id", 0)))
            elif kind == "key":
                phone.key(key=message["key"], event=message.get("event", "keypress"))
            elif kind == "text":
                phone.key(text=message["text"])
            elif kind == "refresh":
                phone.last_input = time.monotonic() - 3
            elif kind == "quit":
                break
        except Exception as exc:  # keep serving other input
            emit({"type": "error", "message": f"input {exc}"})
    phone.close()
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="emulator-<port> on the VDS")
    parser.add_argument("--host", default=ep.DEFAULT_HOST)
    parser.add_argument("--user", default="root")
    parser.add_argument("--key", default=str(ep.DEFAULT_KEY))
    parser.add_argument("--mode", choices=("webrtc", "screenshot"), default="webrtc")
    parser.add_argument("--width", type=int, default=0, help="screenshot-mode frame width (0 = native)")
    args = parser.parse_args()
    try:
        endpoint = discover(args.host, Path(args.key).expanduser(), args.user, args.serial)
        ep.ensure_tunnel(args.host, Path(args.key).expanduser(),
                         {endpoint.local_grpc_port: endpoint.grpc_port}, args.user)
        from viewer import Phone
        phone = Phone(f"127.0.0.1:{endpoint.local_grpc_port}", ep.metadata(endpoint), args.width, 512 * 1024)
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        return 1
    emit({"type": "info", "avd": endpoint.avd, "deviceWidth": phone.device_width,
          "deviceHeight": phone.device_height, "mode": args.mode,
          "grpcPort": endpoint.local_grpc_port})
    threading.Thread(target=input_loop, args=(phone,), daemon=True).start()
    phone.start_stream(args.mode)
    last_state = None
    while True:
        try:
            image = phone.frames.get(timeout=1.0)
        except queue.Empty:
            image = False
        if phone.rtc is not None and phone.rtc.state != last_state:
            last_state = phone.rtc.state
            emit({"type": "state", "state": last_state})
        if image is None:
            emit({"type": "error", "message": "stream ended"})
            break
        if image:
            w, h, data = frame_bytes(image)
            emit({"type": "frame", "w": w, "h": h, "format": "rgb24", "frames": phone.stats["frames"]}, data)
    phone.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
