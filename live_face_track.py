#!/usr/bin/env python3
"""Keep a camera face aligned to an oval in the rendered app preview via OBS WebSocket.

The feedback image is the visible Android Emulator window, rather than the
source video. This matters for apps which mirror, crop, or translate a front
camera stream after the camera provider has delivered it.

OBS owns the virtual camera (`--startvirtualcam` with scene `EMU Front Camera`
and media source `Looping Front Camera Video` on a 1080x1440 canvas). Rather
than recropping the source video or opening a competing `pyvirtualcam` stream,
this script translates and scales the active OBS scene item directly through
OBS WebSocket (`SetSceneItemTransform`).

    .venv/bin/python3 live_face_track.py --serial emulator-5554 --tap-ready
"""

import argparse
import base64
import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

try:
    import cv2
    import mediapipe as mp
    import numpy as np
except ImportError as exc:
    sys.exit(f"missing camera tracking dependency: {exc}")


ROOT = Path(__file__).resolve().parent
DEFAULT_OBS_CONFIG = Path(
    "~/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
).expanduser()
DEFAULT_SCENE_NAME = "EMU Front Camera"
DEFAULT_SOURCE_NAME = "Looping Front Camera Video"


def classify_banner_instruction(hsv, r0, r1, c0, c1):
    """Classify the white text inside Tinder's top instruction banner.

    Returns one of: 'move_closer', 'move_away', 'hold_steady', 'head_straight'.
    """
    bh, bw = r1 - r0 + 1, c1 - c0 + 1
    if bh < 12 or bw < 60:
        return "move_closer"
    ir0, ir1 = r0 + int(bh * 0.14), r1 - int(bh * 0.12)
    ic0, ic1 = c0 + int(bw * 0.08), c1 - int(bw * 0.08)
    crop = hsv[ir0:ir1, ic0:ic1]
    white = ((crop[:, :, 1] < 55) & (crop[:, :, 2] > 185)).astype(np.uint8)
    cols = np.where(white.sum(axis=0) > 0)[0]
    rows = np.where(white.sum(axis=1) > 0)[0]
    if len(cols) < 10 or len(rows) < 5:
        return "move_closer"
    text_w = (cols[-1] - cols[0] + 1) / bw
    mid_c = (cols[0] + cols[-1]) // 2
    left_rows = np.where(white[:, :mid_c].sum(axis=1) > 0)[0]
    right_rows = np.where(white[:, mid_c:].sum(axis=1) > 0)[0]
    descender_ratio = (
        (right_rows[-1] - left_rows[-1]) / bh
        if (len(left_rows) and len(right_rows))
        else 0.0
    )
    _num_labels, _, stats, _ = cv2.connectedComponentsWithStats(white)
    letters = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= max(4, bh * bw * 0.001)]
    letters.sort(key=lambda s: s[cv2.CC_STAT_LEFT])
    # "Hold your head straight" has 4 words (~19 letters) and spans >70% of banner width
    if text_w > 0.70 or len(letters) >= 14:
        return "head_straight"
    if len(letters) >= 4:
        first_h = letters[0][cv2.CC_STAT_HEIGHT]
        first_w = letters[0][cv2.CC_STAT_WIDTH]
        # In "Hold Steady" / "Hold still", letter 2 ('l') and letter 3 ('d') are tall
        # ascenders, whereas in "Move ...", letter 2 ('v') and 3 ('e') are short.
        if (
            letters[2][cv2.CC_STAT_HEIGHT] >= first_h * 0.86
            and letters[3][cv2.CC_STAT_HEIGHT] >= first_h * 0.86
        ) or (first_w < first_h * 0.82 and letters[2][cv2.CC_STAT_HEIGHT] >= first_h * 0.84):
            return "hold_steady"
    if descender_ratio > 0.04 or text_w < 0.52 or len(letters) <= 8:
        return "move_away"
    return "move_closer"


def detect_oval_and_banner(image):
    """Return (oval, instruction) for the live Tinder selfie oval.

    instruction is one of: None (no banner), 'move_closer', 'move_away', 'hold_steady'.
    Rejects smaller or off-center red ellipses on Tinder's instructional/failure
    screens and preserves oval detection when a solid banner overlaps the top of the oval.
    """
    if image is None:
        return None, None
    ih, iw = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = (
        cv2.inRange(hsv, np.array([0, 90, 90]), np.array([12, 255, 255]))
        | cv2.inRange(hsv, np.array([165, 90, 90]), np.array([180, 255, 255]))
    )
    red_strict = (
        cv2.inRange(hsv, np.array([0, 110, 110]), np.array([12, 255, 255]))
        | cv2.inRange(hsv, np.array([165, 110, 110]), np.array([180, 255, 255]))
    )
    row_red_frac = (red_strict > 0).mean(axis=1)
    banner_rows = np.where((row_red_frac > 0.30) & (np.arange(ih) < ih * 0.45))[0]
    has_red_banner = len(banner_rows) >= max(8, int(ih * 0.02))

    # Also detect a dark/black or green banner at the top of the oval (used by 'Hold Steady')
    dark_mask = (hsv[:, :, 2] < 65).astype(np.uint8)
    row_dark_frac = dark_mask.mean(axis=1)
    dark_banner_rows = np.where(
        (row_dark_frac > 0.40) & (np.arange(ih) >= ih * 0.10) & (np.arange(ih) < ih * 0.42)
    )[0]
    has_dark_banner = len(dark_banner_rows) >= max(8, int(ih * 0.02))

    instruction = None
    ring = red.copy()
    if has_red_banner:
        r0, r1 = int(banner_rows.min()), int(banner_rows.max())
        ring[max(0, r0 - 3) : min(ih, r1 + 5), :] = 0
        banner_cols = np.where(red_strict[r0 : r1 + 1, :].mean(axis=0) > 0.5)[0]
        if len(banner_cols) >= 20:
            c0, c1 = int(banner_cols.min()), int(banner_cols.max())
            instruction = classify_banner_instruction(hsv, r0, r1, c0, c1)
        else:
            instruction = "move_closer"
    elif has_dark_banner:
        r0, r1 = int(dark_banner_rows.min()), int(dark_banner_rows.max())
        ring[max(0, r0 - 3) : min(ih, r1 + 5), :] = 0
        instruction = "hold_steady"

    ring[int(ih * 0.90) :, :] = 0

    contours, _ = cv2.findContours(ring, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    candidate_rects = []
    for contour in contours:
        if len(contour) < 20:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        cx_rect = x + width / 2.0
        # Exclude the solid red TINDER logo near the bottom of the screen
        if y > ih * 0.70 and height < ih * 0.12:
            continue
        if width < iw * 0.38 or not (iw * 0.32 <= cx_rect <= iw * 0.62):
            continue
        candidate_rects.append((x, y, width, height))

    if not candidate_rects:
        return None, None
    max_width = max(r[2] for r in candidate_rects)
    arc_pts = []
    for x, y, width, height in candidate_rects:
        if width < max_width * 0.80:
            continue
        for ry in range(y + 2, y + height - 2):
            xs = np.where(ring[ry, x : x + width] > 0)[0]
            if len(xs) >= 2 and (xs[-1] - xs[0]) >= width * 0.25:
                arc_pts.append([x + int(xs[0]), ry])
                arc_pts.append([x + int(xs[-1]), ry])

    if len(arc_pts) < 20:
        return None, None
    pts_arr = np.array(arc_pts, dtype=np.int32)
    y_span = int(pts_arr[:, 1].max() - pts_arr[:, 1].min())
    if y_span < ih * 0.24:
        return None, None
    (cx, cy), (axis_a, axis_b), angle = cv2.fitEllipse(pts_arr)
    ellipse_w, ellipse_h = sorted((axis_a, axis_b))
    if (
        ellipse_w < iw * 0.40
        or ellipse_h < ih * 0.28
        or ellipse_h > ih * 0.88
        or ellipse_h < ellipse_w * 1.20
        or not (iw * 0.35 <= cx <= iw * 0.58)
    ):
        return None, None
    return (cx, cy, ellipse_w, ellipse_h, angle), instruction


def detect_oval(image):
    """Return the strongest portrait red guide ellipse in image pixels."""
    oval, _ = detect_oval_and_banner(image)
    return oval


def detect_failure_screen(image, detector=None):
    """Return True when Tinder's 'Let's try that again' screen is shown."""
    if image is None:
        return False
    oval, _ = detect_oval_and_banner(image)
    if oval is not None:
        return False
    ih, iw = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = (
        cv2.inRange(hsv, np.array([0, 110, 110]), np.array([12, 255, 255]))
        | cv2.inRange(hsv, np.array([165, 110, 110]), np.array([180, 255, 255]))
    )
    red[int(ih * 0.65) :, :] = 0
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    for contour in contours:
        if len(contour) < 20:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        cx = x + w / 2.0
        # The 'Ideal pose' reference ellipse sits on the right card (cx > 0.55 * iw).
        if iw * 0.22 <= w <= iw * 0.42 and ih * 0.18 <= h <= ih * 0.35 and cx > iw * 0.55:
            return True
    if detector is not None:
        for fx, fy, fw, _fh, _score, _iw, _ih, _ew in detect_faces(image, detector):
            # 'Your selfie' card sits on the left half of the retry screen with no red oval
            if fx < iw * 0.38 and ih * 0.25 <= fy <= ih * 0.52 and fw < iw * 0.36:
                return True
    return False


def make_detector(model_path, confidence):
    return mp.tasks.vision.FaceDetector.create_from_options(
        mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            min_detection_confidence=confidence,
        )
    )


def detect_faces(image, detector):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    faces = []
    ih, iw = image.shape[:2]
    for detection in result.detections:
        box = detection.bounding_box
        # BlazeFace keypoints 0 and 1 are the eye centers; 4 and 5 are the ears/tragions.
        # Blending ear midpoint with eye midpoint centers the full head horizontally
        # even when the subject's head is slightly turned.
        if len(detection.keypoints) >= 2:
            left_eye, right_eye = detection.keypoints[:2]
            eye_x = (left_eye.x + right_eye.x) * iw / 2
            eye_y = (left_eye.y + right_eye.y) * ih / 2
            eye_width = abs(right_eye.x - left_eye.x) * iw
            if len(detection.keypoints) >= 6:
                right_ear, left_ear = detection.keypoints[4], detection.keypoints[5]
                ear_x = (right_ear.x + left_ear.x) * iw / 2
                anchor_x = 0.55 * ear_x + 0.45 * eye_x
            else:
                anchor_x = eye_x
            anchor_y = eye_y
        else:
            anchor_x = box.origin_x + box.width / 2
            anchor_y = box.origin_y + box.height * 0.4
            eye_width = box.width * 0.42
        faces.append(
            (
                anchor_x,
                anchor_y,
                float(box.width),
                float(box.height),
                detection.categories[0].score,
                iw,
                ih,
                eye_width,
            )
        )
    return faces


def face_in_oval(faces, oval):
    if oval is None:
        return None
    ox, oy, ow, oh, _ = oval
    inside = [
        face
        for face in faces
        if abs(face[0] - ox) <= ow * 0.75 and abs(face[1] - oy) <= oh * 0.75
    ]
    return max(inside, default=None, key=lambda face: face[2] * face[3])


def measure_alignment(image, detector):
    """Return screen-space and normalized oval-minus-face errors and fill ratio."""
    oval, banner_instruction = detect_oval_and_banner(image)
    if oval is None:
        return None
    face = face_in_oval(detect_faces(image, detector), oval)
    if face is None:
        return None
    ox, oy, ow, oh, _ = oval
    fx, fy, _fw, _fh, _score, iw, ih, eye_width = face

    # Check if the 'I'm ready' button below the oval is present (pre-ready screen).
    by = min(ih - 1, int(round(oy + oh * 0.5 + ih * 0.105)))
    bx = min(iw - 1, max(0, int(round(ox - ow * 0.25))))
    b_pixel = image[by, bx]
    is_pre_ready_oval = (banner_instruction is None) and (oh < ih * 0.42)
    ready_button_present = bool(np.mean(b_pixel) < 235) and is_pre_ready_oval
    ready_button_enabled = bool(np.mean(b_pixel) < 80) and is_pre_ready_oval

    if banner_instruction in ("move_closer", "move_away", "hold_steady", "head_straight"):
        instruction = banner_instruction
    elif is_pre_ready_oval:
        instruction = "pre_ready"
    else:
        instruction = "hold_steady"

    move_closer = instruction == "move_closer"
    move_away = instruction == "move_away"
    hold_steady = instruction == "hold_steady"

    # Place eyes slightly above the oval center so the whole face (forehead to chin)
    # sits centered inside the oval rather than pushed into the top.
    target_eye_y = oy - oh * (0.04 if instruction == "pre_ready" else 0.03)
    horizontal_error = ox - fx
    vertical_error = target_eye_y - fy

    return {
        "horizontal_error": float(horizontal_error),
        "vertical_error": float(vertical_error),
        "desired_face_landmark_y": float(target_eye_y),
        "rendered_face_center_x": float(fx),
        "rendered_face_landmark_y": float(fy),
        "oval_center_x": float(ox),
        "oval_center_y": float(oy),
        "oval_width": float(ow),
        "oval_height": float(oh),
        "error_x": float(horizontal_error / ow),
        "error_y": float(vertical_error / oh),
        "face_fill": float(eye_width / ow),
        "instruction": instruction,
        "move_closer": bool(move_closer),
        "move_away": bool(move_away),
        "hold_steady": bool(hold_steady),
        "ready_button_present": ready_button_present,
        "ready_button_enabled": ready_button_enabled,
        "oval": oval,
        "face": face,
    }


def avd_name(serial, adb="adb"):
    value = subprocess.check_output(
        [adb, "-s", serial, "emu", "avd", "name"], timeout=5, text=True
    )
    name = value.splitlines()[0].strip()
    if not name:
        raise RuntimeError(f"could not identify {serial}")
    return name


class EmulatorWindowCapture:
    """Capture one emulator window, including Android FLAG_SECURE surfaces."""

    def __init__(self, avd, serial="emulator-5554", adb="adb"):
        self.avd = avd
        self.serial = serial
        self.adb = adb
        helper = ROOT / "capture_emulator_window.sh"
        result = subprocess.run(
            ["bash", str(helper), "--window-id", avd],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.window_id = result.stdout.strip().splitlines()[-1]
        if not self.window_id.isdigit():
            raise RuntimeError(f"invalid emulator window id: {self.window_id!r}")

    def capture(self):
        handle, name = tempfile.mkstemp(prefix="face-track-window-", suffix=".png")
        os.close(handle)
        path = Path(name)
        path.unlink()
        try:
            try:
                res = subprocess.run(
                    ["/usr/sbin/screencapture", "-x", "-o", "-l", self.window_id, str(path)],
                    timeout=3,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                ok = res.returncode == 0 and path.is_file()
            except subprocess.TimeoutExpired:
                ok = False
            if not ok:
                try:
                    subprocess.run(
                        [
                            self.adb,
                            "-s",
                            self.serial,
                            "emu",
                            "screenrecord",
                            "screenshot",
                            str(path),
                        ],
                        check=True,
                        timeout=5,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    return None
            return cv2.imread(str(path))
        finally:
            path.unlink(missing_ok=True)


class OBSWebSocketClient:
    """Minimal OBS WebSocket v5 client for controlling a scene item transform."""

    def __init__(
        self,
        host="127.0.0.1",
        port=None,
        password=None,
        config_path=DEFAULT_OBS_CONFIG,
        scene_name=DEFAULT_SCENE_NAME,
        source_name=DEFAULT_SOURCE_NAME,
    ):
        cfg = {}
        if config_path and Path(config_path).expanduser().is_file():
            cfg = json.loads(Path(config_path).expanduser().read_text())
        self.host = host
        self.port = int(port or cfg.get("server_port") or 4455)
        self.password = password if password is not None else cfg.get("server_password", "")
        self.scene_name = scene_name
        self.source_name = source_name
        self.sock = None
        self._rx_buf = b""
        self.req_id = 0
        self._lock = threading.RLock()
        self.scene_item_id = None
        self.canvas_width = 1080.0
        self.canvas_height = 1440.0
        self.source_width = 1080.0
        self.source_height = 1440.0

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("OBS WebSocket closed during HTTP handshake")
            response += chunk
        _headers, self._rx_buf = response.split(b"\r\n\r\n", 1)

        hello = self._recv_json()
        if hello.get("op") != 0:
            raise RuntimeError(f"unexpected OBS WebSocket hello: {hello}")
        auth_info = hello.get("d", {}).get("authentication")
        ident = {"op": 1, "d": {"rpcVersion": 1}}
        if auth_info:
            secret = base64.b64encode(
                hashlib.sha256((self.password + auth_info["salt"]).encode("utf-8")).digest()
            ).decode("ascii")
            auth = base64.b64encode(
                hashlib.sha256((secret + auth_info["challenge"]).encode("utf-8")).digest()
            ).decode("ascii")
            ident["d"]["authentication"] = auth
        self._send_json(ident)
        identified = self._recv_json()
        if identified.get("op") != 2:
            raise RuntimeError(f"OBS WebSocket authentication failed: {identified}")

        video_settings = self.request("GetVideoSettings")
        self.canvas_width = float(video_settings.get("baseWidth", 1080.0))
        self.canvas_height = float(video_settings.get("baseHeight", 1440.0))

        item_resp = self.request(
            "GetSceneItemId",
            {"sceneName": self.scene_name, "sourceName": self.source_name},
        )
        self.scene_item_id = int(item_resp["sceneItemId"])
        try:
            self.request(
                "SetSceneItemScaleFilter",
                {
                    "sceneName": self.scene_name,
                    "sceneItemId": self.scene_item_id,
                    "scaleFilter": "OBS_SCALE_LANCZOS",
                },
            )
        except Exception:
            pass
        transform = self.get_transform()
        self.source_width = float(transform.get("sourceWidth") or self.canvas_width)
        self.source_height = float(transform.get("sourceHeight") or self.canvas_height)
        return transform

    def _recv_exact(self, n):
        while len(self._rx_buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._rx_buf)))
            if not chunk:
                raise RuntimeError("OBS WebSocket connection closed")
            self._rx_buf += chunk
        out, self._rx_buf = self._rx_buf[:n], self._rx_buf[n:]
        return out

    def _recv_json(self):
        while True:
            hdr = self._recv_exact(2)
            opcode = hdr[0] & 0x0F
            length = hdr[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length)
            if opcode == 0x8:
                raise RuntimeError("OBS WebSocket closed by server")
            if opcode in (0x9, 0xA):
                continue
            return json.loads(payload.decode("utf-8"))

    def _send_json(self, obj):
        payload = json.dumps(obj).encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.unpack("2B", struct.pack(">H", n)))
        else:
            header.append(0x80 | 127)
            header.extend(struct.unpack("8B", struct.pack(">Q", n)))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def request(self, request_type, request_data=None):
        with self._lock:
            self.req_id += 1
            req_id = f"req-{self.req_id}"
            msg = {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": req_id,
                    "requestData": request_data or {},
                },
            }
            self._send_json(msg)
            while True:
                resp = self._recv_json()
                if resp.get("op") == 7 and resp.get("d", {}).get("requestId") == req_id:
                    status = resp["d"].get("requestStatus", {})
                    if not status.get("result", False):
                        raise RuntimeError(f"OBS {request_type} failed: {status}")
                    return resp["d"].get("responseData", {})

    def get_transform(self):
        data = self.request(
            "GetSceneItemTransform",
            {"sceneName": self.scene_name, "sceneItemId": self.scene_item_id},
        )
        return data["sceneItemTransform"]

    def set_transform(self, position_x, position_y, scale):
        self.request(
            "SetSceneItemTransform",
            {
                "sceneName": self.scene_name,
                "sceneItemId": self.scene_item_id,
                "sceneItemTransform": {
                    "alignment": 5,
                    "boundsType": "OBS_BOUNDS_NONE",
                    "cropLeft": 0,
                    "cropRight": 0,
                    "cropTop": 0,
                    "cropBottom": 0,
                    "positionX": float(position_x),
                    "positionY": float(position_y),
                    "scaleX": float(scale),
                    "scaleY": float(scale),
                },
            },
        )

    def set_media_file(self, file_path):
        cur = self.request("GetInputSettings", {"inputName": self.source_name})
        settings = cur.get("inputSettings", {})
        resolved = str(Path(file_path).expanduser().resolve())
        if settings.get("local_file") != resolved:
            self.request(
                "SetInputSettings",
                {
                    "inputName": self.source_name,
                    "inputSettings": {
                        "local_file": resolved,
                        "is_local_file": True,
                        "looping": True,
                    },
                    "overlay": True,
                },
            )

    def set_media_speed(self, speed_percent):
        cur = self.request("GetInputSettings", {"inputName": self.source_name})
        settings = cur.get("inputSettings", {})
        if int(settings.get("speed_percent", 100)) != int(speed_percent):
            self.request(
                "SetInputSettings",
                {
                    "inputName": self.source_name,
                    "inputSettings": {"speed_percent": int(speed_percent)},
                    "overlay": True,
                },
            )

    def set_media_paused(self, paused):
        action = (
            "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
            if paused
            else "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
        )
        self.request(
            "TriggerMediaInputAction",
            {"inputName": self.source_name, "mediaAction": action},
        )

    def pulse_slow_frame(self, play_seconds=0.035):
        self.set_media_paused(False)
        time.sleep(play_seconds)
        self.set_media_paused(True)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


@dataclass
class ControlState:
    position_x: float = 0.0
    position_y: float = 0.0
    scale: float = 1.08
    measurements: int = 0
    aligned: int = 0
    last: dict | None = None
    ready_tapped: bool = False


def _spring_step(cur: float, vel: float, target: float, dt: float, omega: float, max_speed: float):
    """Critically damped velocity-smoothed step toward target with human speed limit."""
    err = target - cur
    desired_vel = float(np.clip(omega * err, -max_speed, max_speed))
    blend = min(1.0, 2.2 * omega * dt)
    new_vel = vel + blend * (desired_vel - vel)
    new_cur = cur + new_vel * dt
    if (err >= 0.0 and new_cur > target) or (err <= 0.0 and new_cur < target):
        if abs(err) < max_speed * dt:
            new_cur = target
            new_vel = 0.0
    return float(new_cur), float(new_vel)


class SmoothTransformAnimator:
    """60 Hz OBS scene item transform animator for natural human-like motion and zooming.

    Instead of jumping position/scale at the screenshot capture rate (~3-5 Hz),
    this thread updates OBS at 60 Hz with:
    - Critically damped velocity easing and human movement speed caps
    - Per-frame pivot compensation so zooming in/out never shifts the face off-center
    - Subtle organic handheld micro-sway (breathing + wrist posture Lissajous motion)
    """

    def __init__(
        self,
        obs: OBSWebSocketClient,
        init_x: float,
        init_y: float,
        init_scale: float,
        base_scale: float = 1.0,
        fps: float = 60.0,
        sway_enabled: bool = True,
    ):
        self.obs = obs
        self.base_scale = float(base_scale)
        self.fps = float(fps)
        self.sway_enabled = bool(sway_enabled)
        self._lock = threading.Lock()
        self.cur_x = float(init_x)
        self.cur_y = float(init_y)
        self.cur_scale = float(init_scale)
        self.target_x = float(init_x)
        self.target_y = float(init_y)
        self.target_scale = float(init_scale)
        self.vx = 0.0
        self.vy = 0.0
        self.vscale = 0.0
        self.instruction = "pre_ready"
        self._stop_event = threading.Event()
        self._thread = None
        self._t0 = time.monotonic()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="obs-60hz-animator", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def get_current(self):
        with self._lock:
            return self.cur_x, self.cur_y, self.cur_scale

    def set_target(self, target_x: float, target_y: float, target_scale: float, instruction: str = "pre_ready"):
        with self._lock:
            self.target_x = float(target_x)
            self.target_y = float(target_y)
            self.target_scale = float(target_scale)
            self.instruction = instruction or "pre_ready"

    def hold_current(self, instruction: str = "hold_steady"):
        with self._lock:
            self.target_x = self.cur_x
            self.target_y = self.cur_y
            self.target_scale = self.cur_scale
            self.instruction = instruction

    def reset_immediate(self, x: float, y: float, scale: float, instruction: str = "pre_ready"):
        with self._lock:
            self.cur_x = float(x)
            self.cur_y = float(y)
            self.cur_scale = float(scale)
            self.target_x = float(x)
            self.target_y = float(y)
            self.target_scale = float(scale)
            self.vx = 0.0
            self.vy = 0.0
            self.vscale = 0.0
            self.instruction = instruction
        try:
            self.obs.set_transform(x, y, scale)
        except Exception:
            pass

    def step_dt(self, dt: float, elapsed_t: float):
        cw = self.obs.canvas_width
        ch = self.obs.canvas_height
        pivot_x = cw * 0.414
        pivot_y = ch * 0.538

        with self._lock:
            instr = self.instruction
            if instr in ("move_closer", "move_away"):
                omega_s = 4.2
                max_s_speed = 0.25 * self.base_scale
                omega_p = 5.5
                max_p_speed = 240.0
            elif instr in ("hold_steady", "head_straight"):
                omega_s = 6.0
                max_s_speed = 0.08 * self.base_scale
                omega_p = 3.5
                max_p_speed = 90.0
            else:
                omega_s = 4.5
                max_s_speed = 0.20 * self.base_scale
                omega_p = 6.0
                max_p_speed = 250.0

            old_scale = self.cur_scale
            new_scale, self.vscale = _spring_step(
                old_scale, self.vscale, self.target_scale, dt, omega_s, max_s_speed
            )
            d_scale = new_scale - old_scale
            self.cur_scale = new_scale

            # Shift current position by exact pivot delta for this 60Hz sub-step so
            # zooming never pulls the face sideways or vertically on intermediate frames.
            pivot_step = d_scale / self.base_scale
            self.cur_x -= pivot_step * pivot_x
            self.cur_y -= pivot_step * pivot_y

            # Target position at the current intermediate scale:
            rem_pivot = (self.target_scale - new_scale) / self.base_scale
            eff_target_x = self.target_x + rem_pivot * pivot_x
            eff_target_y = self.target_y + rem_pivot * pivot_y

            self.cur_x, self.vx = _spring_step(
                self.cur_x, self.vx, eff_target_x, dt, omega_p, max_p_speed
            )
            self.cur_y, self.vy = _spring_step(
                self.cur_y, self.vy, eff_target_y, dt, omega_p, max_p_speed
            )

            out_x = self.cur_x
            out_y = self.cur_y
            out_scale = self.cur_scale

        if self.sway_enabled:
            sway_amp = 0.55 if instr in ("hold_steady", "head_straight") else 1.0
            sway_x = sway_amp * (
                1.5 * math.sin(2.0 * math.pi * 0.41 * elapsed_t)
                + 0.7 * math.cos(2.0 * math.pi * 0.93 * elapsed_t)
            )
            sway_y = sway_amp * (
                1.9 * math.sin(2.0 * math.pi * 0.29 * elapsed_t + 0.6)
                + 0.8 * math.sin(2.0 * math.pi * 0.77 * elapsed_t + 1.4)
            )
            sway_scale = (
                sway_amp
                * self.base_scale
                * (0.0016 * math.sin(2.0 * math.pi * 0.34 * elapsed_t + 1.1))
            )
            out_x += sway_x
            out_y += sway_y
            out_scale += sway_scale

        return out_x, out_y, out_scale

    def _run(self):
        period = 1.0 / max(10.0, self.fps)
        last_t = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            dt = min(0.05, max(0.001, now - last_t))
            last_t = now
            out_x, out_y, out_scale = self.step_dt(dt, now - self._t0)
            try:
                self.obs.set_transform(out_x, out_y, out_scale)
            except Exception:
                pass
            spent = time.monotonic() - now
            wait = period - spent
            if wait > 0:
                self._stop_event.wait(wait)


def compute_next_obs_transform(
    state: ControlState,
    measurement: dict,
    canvas_width: float = 1080.0,
    canvas_height: float = 1440.0,
    gain: float = 0.45,
    mirrored: bool = True,
    desired_fill: float = 0.44,
    move_closer_fill: float = 0.46,
    base_scale: float = 1.0,
):
    """Compute the next OBS (position_x, position_y, scale) from Tinder screen error.

    - horizontal_error = oval_center_x - rendered_face_center_x
    - vertical_error = desired_face_landmark_y - rendered_face_landmark_y
    - Only scale up aggressively when Tinder shows 'Move closer'; on the initial
      'Get ready for your video selfie' screen, keep a comfortable framing
      (~1.08-1.22x * base_scale) so Tinder enables the 'I'm ready' button.
    """
    ex = measurement["error_x"]
    ey = measurement["error_y"]
    face_fill = measurement["face_fill"]
    instruction = measurement.get("instruction") or (
        "move_closer" if measurement.get("move_closer") else "pre_ready"
    )

    old_scale = state.scale
    if instruction == "move_closer":
        fill_error = max(0.055, move_closer_fill - face_fill)
        step_scale = float(np.clip(gain * fill_error * 1.35, 0.055, 0.095)) * base_scale
        new_scale = float(np.clip(old_scale + step_scale, 0.95 * base_scale, 1.65 * base_scale))
    elif instruction == "move_away":
        fill_error = min(-0.040, desired_fill - face_fill)
        step_scale = float(np.clip(gain * fill_error * 1.4, -0.075, -0.035)) * base_scale
        new_scale = float(np.clip(old_scale + step_scale, 0.72 * base_scale, 1.45 * base_scale))
    elif instruction in ("hold_steady", "head_straight"):
        new_scale = old_scale
    else:
        fill_error = desired_fill - face_fill
        step_scale = float(np.clip(gain * fill_error * 1.2, -0.045, 0.045)) * base_scale
        new_scale = float(np.clip(old_scale + step_scale, 0.78 * base_scale, 1.24 * base_scale))
    d_scale = new_scale - old_scale

    # Compensate top-left position for scale change around the empirical oval pivot
    pivot_scale = d_scale / base_scale
    pos_x = state.position_x - pivot_scale * (canvas_width * 0.414)
    pos_y = state.position_y - pivot_scale * (canvas_height * 0.538)

    # Empirical response on 1080x1440 OBS canvas feeding Tinder:
    # 1 oval width (~574 screen px) corresponds to ~650 OBS canvas px.
    # 1 oval height (~850 screen px) corresponds to ~965 OBS canvas px.
    eff_gain = gain * 0.30 if instruction == "hold_steady" else gain
    x_sign = -1.0 if mirrored else 1.0
    step_x = np.clip(x_sign * eff_gain * ex * (canvas_width * 0.60), -140.0, 140.0)
    step_y = np.clip(eff_gain * ey * (canvas_height * 0.67), -140.0, 140.0)

    pos_x = float(pos_x + step_x)
    pos_y = float(pos_y + step_y)

    # Keep the scaled media layer within safe bounds so the oval stays filled
    eff_vis_scale = new_scale / base_scale
    min_x = canvas_width * (1.0 - eff_vis_scale) - 360.0
    max_x = 360.0
    min_y = canvas_height * (1.0 - eff_vis_scale) - 360.0
    max_y = 360.0
    pos_x = float(np.clip(pos_x, min_x, max_x))
    pos_y = float(np.clip(pos_y, min_y, max_y))
    return pos_x, pos_y, new_scale


def camera_layer_frame(frame, width, height, shift_x, shift_y, zoom=1.0):
    """Translate a complete 3:4 camera layer without recentering the source face."""
    portrait_width = round(height * 3 / 4)
    target_ratio = portrait_width / height
    source_h, source_w = frame.shape[:2]
    if source_w / source_h > target_ratio:
        crop_h, crop_w = source_h, round(source_h * target_ratio)
    else:
        crop_w, crop_h = source_w, round(source_w / target_ratio)
    x = (source_w - crop_w) // 2
    y = (source_h - crop_h) // 2
    crop = frame[y : y + crop_h, x : x + crop_w]
    portrait = cv2.resize(crop, (portrait_width, height), interpolation=cv2.INTER_LANCZOS4)
    left = (width - portrait_width) // 2
    right = width - portrait_width - left
    layer = cv2.copyMakeBorder(portrait, 0, 0, left, right, cv2.BORDER_REPLICATE)
    matrix = np.array(
        [
            [zoom, 0, shift_x * portrait_width + (1 - zoom) * width / 2],
            [0, zoom, shift_y * height + (1 - zoom) * height / 2],
        ],
        dtype=np.float32,
    )
    return cv2.warpAffine(
        layer, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )


def tap_device_ready(serial, measurement, adb="adb"):
    oval = measurement["oval"]
    face = measurement["face"]
    image_w, image_h = face[5], face[6]
    ox, oy, _ow, oh, _angle = oval
    content_w = min(image_w, image_h * 1080 / 2340)
    content_h = content_w * 2340 / 1080
    top = max(0.0, image_h - content_h)
    button_y = min(top + content_h * 0.72, oy + oh * 0.5 + content_h * 0.11)
    device_x = round(ox / content_w * 1080)
    device_y = round((button_y - top) / content_h * 2340)
    subprocess.run(
        [adb, "-s", serial, "shell", "input", "tap", str(device_x), str(device_y)],
        check=True,
        timeout=5,
    )


def tap_device_try_again(serial, adb="adb"):
    subprocess.run(
        [adb, "-s", serial, "shell", "input", "swipe", "540", "1600", "540", "900", "180"],
        check=False,
        timeout=5,
    )
    time.sleep(0.4)
    subprocess.run(
        [adb, "-s", serial, "shell", "input", "tap", "540", "1595"],
        check=True,
        timeout=5,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--video", type=Path, help="optional compatibility arg (OBS owns media source)")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--avd", help="defaults to the AVD running on --serial")
    parser.add_argument("--obs-scene", default=DEFAULT_SCENE_NAME)
    parser.add_argument("--obs-source", default=DEFAULT_SOURCE_NAME)
    parser.add_argument("--obs-config", type=Path, default=DEFAULT_OBS_CONFIG)
    parser.add_argument("--screen-interval", type=float, default=0.16)
    parser.add_argument("--gain", type=float, default=0.50)
    parser.add_argument("--desired-fill", type=float, default=0.44)
    parser.add_argument("--move-closer-fill", type=float, default=0.46)
    parser.add_argument("--speed-percent", type=int, default=30, help="OBS playback speed percent")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.045,
        help="center tolerance as a fraction of oval dimensions",
    )
    parser.add_argument("--stable-count", type=int, default=4)
    parser.add_argument(
        "--preview-mirrored",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="invert horizontal feedback for a mirrored front preview",
    )
    parser.add_argument("--tap-ready", action="store_true")
    parser.add_argument(
        "--auto-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="automatically tap 'Try again' if Tinder is on the retry screen",
    )
    parser.add_argument("--max-steps", type=int, default=0, help="stop after N steps (0=unlimited)")
    parser.add_argument("--save-aligned", type=Path, help="save a screenshot once aligned")
    parser.add_argument("--confidence", type=float, default=0.40)
    args = parser.parse_args(argv)

    avd = args.avd or avd_name(args.serial)
    model = ROOT / "models" / "blaze_face_short_range.tflite"
    if not model.is_file():
        parser.error(f"face model not found: {model}")

    obs = OBSWebSocketClient(
        config_path=args.obs_config,
        scene_name=args.obs_scene,
        source_name=args.obs_source,
    )
    initial_tf = obs.connect()
    print(
        f"Connected to OBS WebSocket on port {obs.port}: scene={obs.scene_name!r}, "
        f"source={obs.source_name!r} (id={obs.scene_item_id}), "
        f"canvas={int(obs.canvas_width)}x{int(obs.canvas_height)}",
        flush=True,
    )

    # Set a smooth base playback speed so the subject in the clip does not lunge
    if args.video:
        obs.set_media_file(args.video)
    obs.set_media_speed(args.speed_percent)
    obs.set_media_paused(False)
    time.sleep(0.15)
    initial_tf = obs.get_transform()
    obs.source_width = float(initial_tf.get("sourceWidth") or obs.canvas_width)
    obs.source_height = float(initial_tf.get("sourceHeight") or obs.canvas_height)
    base_scale = obs.canvas_width / obs.source_width if obs.source_width > 0 else 1.0

    # Start from a well-centered initial OBS transform for the pre-ready oval
    init_scale = float(initial_tf.get("scaleX") or (1.00 * base_scale))
    init_x = float(initial_tf.get("positionX") or 40.0)
    init_y = float(initial_tf.get("positionY") or 80.0)
    if (
        init_scale < 0.78 * base_scale
        or init_scale > 1.26 * base_scale
        or abs(init_x) > 250
        or abs(init_y) > 250
    ):
        init_scale = 1.00 * base_scale
        init_x = 40.0
        init_y = 80.0
        obs.set_transform(init_x, init_y, init_scale)

    state = ControlState(position_x=init_x, position_y=init_y, scale=init_scale)
    animator = SmoothTransformAnimator(
        obs=obs,
        init_x=init_x,
        init_y=init_y,
        init_scale=init_scale,
        base_scale=base_scale,
        fps=60.0,
        sway_enabled=True,
    )
    animator.start()
    detector = make_detector(model, args.confidence)
    capture = EmulatorWindowCapture(avd, serial=args.serial)

    step = 0
    last_retry_tap = 0.0
    last_ready_tap = 0.0
    slow_mode_active = False
    try:
        while args.max_steps <= 0 or step < args.max_steps:
            started = time.monotonic()
            step += 1
            image = capture.capture()
            cur_x, cur_y, cur_scale = animator.get_current()
            state.position_x = cur_x
            state.position_y = cur_y
            state.scale = cur_scale
            measurement = measure_alignment(image, detector)
            if measurement is not None:
                state.measurements += 1
                state.last = measurement
                ex = measurement["error_x"]
                ey = measurement["error_y"]
                hx = measurement["horizontal_error"]
                vy = measurement["vertical_error"]
                fill = measurement["face_fill"]
                instruction = measurement["instruction"]

                # Keep continuous smooth slow-motion playback during 'hold_steady'
                # (1026(6) is 60fps all-intra, so 30% speed gives 18 distinct smooth frames/sec
                # without pause/play stutter)
                if instruction == "hold_steady":
                    slow_mode_active = True
                    obs.set_media_paused(False)
                elif slow_mode_active:
                    slow_mode_active = False
                    obs.set_media_paused(False)

                good = (
                    abs(ex) <= args.tolerance
                    and abs(ey) <= args.tolerance
                    and instruction in ("pre_ready", "hold_steady")
                )
                state.aligned = state.aligned + 1 if good else 0

                if not good:
                    next_x, next_y, next_scale = compute_next_obs_transform(
                        state,
                        measurement,
                        canvas_width=obs.canvas_width,
                        canvas_height=obs.canvas_height,
                        gain=args.gain,
                        mirrored=args.preview_mirrored,
                        desired_fill=args.desired_fill,
                        move_closer_fill=args.move_closer_fill,
                        base_scale=base_scale,
                    )
                    animator.set_target(next_x, next_y, next_scale, instruction=instruction)
                else:
                    animator.hold_current(instruction=instruction)

                print(
                    f"step={step} obs={state.measurements} "
                    f"instr={instruction} "
                    f"px_err=({hx:+.1f},{vy:+.1f}) "
                    f"norm_err=({ex:+.3f},{ey:+.3f}) "
                    f"fill={fill:.3f} slow={slow_mode_active} "
                    f"obs_pos=({state.position_x:+.1f},{state.position_y:+.1f}) "
                    f"obs_scale={state.scale:.3f} "
                    f"target_scale={animator.target_scale:.3f} "
                    f"stable={state.aligned} ready_enabled={measurement['ready_button_enabled']}",
                    flush=True,
                )

                if args.save_aligned and state.aligned >= 1:
                    args.save_aligned.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(args.save_aligned), image)

                if (
                    args.tap_ready
                    and measurement["ready_button_enabled"]
                    and state.aligned >= args.stable_count
                    and (not state.ready_tapped or (time.monotonic() - last_ready_tap) > 2.5)
                ):
                    state.ready_tapped = True
                    last_ready_tap = time.monotonic()
                    state.aligned = 0
                    print("Face aligned in oval and 'I'm ready' is enabled; tapping 'I'm ready' ...", flush=True)
                    tap_device_ready(args.serial, measurement)
            else:
                # If the small pre-ready oval is visible without a face (e.g. returned to pre-ready oval while still zoomed at 1.65x),
                # smoothly glide the OBS transform back to the pre-ready framing so the full face is visible in the oval.
                oval_only, banner_only = detect_oval_and_banner(image)
                if (
                    oval_only is not None
                    and banner_only is None
                    and oval_only[3] < image.shape[0] * 0.42
                    and state.scale > 1.28 * base_scale
                ):
                    state.ready_tapped = False
                    state.aligned = 0
                    state.position_x = 40.0
                    state.position_y = 80.0
                    state.scale = 1.00 * base_scale
                    animator.set_target(state.position_x, state.position_y, state.scale, instruction="pre_ready")
                    if slow_mode_active:
                        slow_mode_active = False
                        obs.set_media_paused(False)
                    print(f"step={step} smoothly resetting zoomed transform for pre-ready oval ...", flush=True)
                    continue
                if args.auto_retry and (time.monotonic() - last_retry_tap) > 4.0:
                    if detect_failure_screen(image, detector):
                        print("Detected Tinder retry screen; tapping 'Try again' ...", flush=True)
                        tap_device_try_again(args.serial)
                        state.ready_tapped = False
                        state.aligned = 0
                        state.position_x = 40.0
                        state.position_y = 80.0
                        state.scale = 1.00 * base_scale
                        animator.set_target(state.position_x, state.position_y, state.scale, instruction="pre_ready")
                        if slow_mode_active:
                            slow_mode_active = False
                            obs.set_media_paused(False)
                        last_retry_tap = time.monotonic()
                        time.sleep(1.2)
                        continue
                print(f"step={step} waiting for live Tinder selfie oval and face ...", flush=True)

            elapsed = time.monotonic() - started
            time.sleep(max(0.02, args.screen_interval - elapsed))
    except KeyboardInterrupt:
        print("Stopping ...", flush=True)
    finally:
        animator.stop()
        detector.close()
        try:
            obs.set_media_paused(False)
        except Exception:
            pass
        obs.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
