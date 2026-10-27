#!/usr/bin/env python3
"""Local/VPS control panel for creator account preparation.

The server deliberately separates preparation from in-app submission. It stores
creator choices, prepares per-account image variants, and can inspect the
currently visible Android screen without clicking it. SMS, terms, CAPTCHA and
identity-verification boundaries remain in the existing guarded signup tools.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import hashlib
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import platform
import random
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DIST = ROOT / "web"
DATA = Path(os.environ.get("ACCOUNT_PANEL_DATA", ROOT / "data")).resolve()
DB = DATA / "control-panel.sqlite3"
UPLOADS = DATA / "uploads"
GENERATED = DATA / "generated"
PHONE_BACKUPS = Path(os.environ.get("PHONE_BACKUPS", Path.home() / "galaxy_s25_avd_backups")).resolve()
DEFAULT_VARIANTS = ROOT / "vendor" / "variants.py"
VARIANTS_PATH = Path(os.environ.get("IG_VARIANTS_PATH", DEFAULT_VARIANTS)).resolve()
MAX_UPLOAD = 30 * 1024 * 1024
MAX_VIDEO_UPLOAD = 512 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
               "video/x-m4v": ".m4v", "application/octet-stream": ""}
PACKAGE_APPS = {"com.bumble.app": "Bumble", "com.tinder": "Tinder",
                "com.pof.android": "Plenty of Fish"}
FLEET_JOBS = {}


TINDER_INTERESTS = ["Atari", "Manga", "Papeda", "Ludo", "Gudeg", "League of Legends", "Food tours", "Maggi", "90s Kid", "Sega", "Sambal", "Foodie", "Harry Potter", "MLB", "Fortnite", "Marvel", "E-Sports", "PlayStation", "Comic-con", "Dungeons & Dragons", "Soto", "Biryani", "Xbox", "Among Us", "NBA", "Sate"]
BUMBLE_INTERESTS = ["Aromatherapy", "Astrology", "Cold plunging", "Crystals", "Deep chats", "Journaling", "Mindfulness", "Nutrition", "Badminton", "Baseball", "Basketball", "Bodybuilding", "Bouldering", "Bowling", "Boxing", "Cardio", "Coffee", "Museums & galleries", "Cats", "Tennis", "Vegetarian", "Dogs", "Festivals", "Yoga", "Art", "Skiing", "Country", "Concerts", "Camping"]


def question(key, label, options=(), *, multiple=False, count=None, kind="choice", note=""):
    return {"key": key, "label": label, "options": list(options), "multiple": multiple,
            "count": count, "kind": kind, "note": note}


APP_SCHEMAS = {
    "bumble": {
        "name": "Bumble", "color": "#F8D72E", "status": "guided",
        "note": "Reviewed from the saved Bumble flow. Choices can be stored now; live availability is checked on-device.",
        "questions": [
            question("first_name", "First name", kind="text"),
            question("birthday", "Birthday", kind="date"),
            question("gender", "Gender", ["Woman", "Man", "Nonbinary"]),
            question("show_gender", "Show gender on profile", ["Yes", "No"]),
            question("dating_intention", "Dating intention", ["A long-term relationship", "A life partner", "Open to seeing where things go", "Something casual", "Marriage", "Ethical non-monogamy"]),
            question("height", "Height", [f"{cm} cm" for cm in range(150, 201)]),
            question("drinking", "Drinking", ["Yes, I drink", "I drink sometimes", "I rarely drink", "No, I don’t drink", "I’m sober"]),
            question("smoking", "Smoking", ["I smoke sometimes", "No, I don’t smoke", "Yes, I smoke", "I’m trying to quit"]),
            question("kids", "Children", ["Have kids", "Don’t have kids"]),
            question("family_plans", "Family plans", ["Don’t want kids", "Open to kids", "Want kids", "Not sure"]),
            question("religion", "Religion", ["Agnostic", "Atheist", "Buddhist", "Catholic", "Christian", "Hindu", "Jain", "Jewish", "Mormon", "Latter-day Saint", "Muslim", "Zoroastrian", "Sikh", "Spiritual", "Other"]),
            question("politics", "Politics", ["Apolitical", "Moderate", "Liberal", "Conservative"]),
            question("ethnicity", "Ethnicity", ["African American", "Black", "Black African", "Black American", "Black Caribbean", "Central Asian", "Chinese Caribbean", "East Asian", "European", "Hispanic", "Jewish", "Indo-Caribbean", "Latina", "Latino", "Latinx", "Middle Eastern", "Native American", "Pacific Islander", "South Asian", "Southeast Asian", "White", "Other"]),
            question("interests", "Interests", BUMBLE_INTERESTS, multiple=True, count=5, note="Saved capture contains these visible options; inspect live screens to extend the catalog."),
        ],
    },
    "tinder": {
        "name": "Tinder", "color": "#FE3C72", "status": "guided",
        "note": "Exact reviewed options from the recorded Tinder onboarding helper.",
        "questions": [
            question("first_name", "First name", kind="text"), question("birthday", "Birthday", kind="date"),
            question("gender", "Gender", ["Woman", "Man"]), question("show_gender", "Show gender on profile", ["Yes", "No"]),
            question("distance", "Distance preference", ["50 Mi"]),
            question("relationship_goal", "Relationship goal", ["Long-term partner", "Long-term, open to short", "Short-term, open to long", "Short-term fun", "New friends", "Still figuring it out"]),
            question("drinking", "How often do you drink?", ["Not for me", "Sober", "Sober curious", "On special occasions", "Socially on weekends", "Most Nights"]),
            question("smoking", "How often do you smoke?", ["Social smoker", "Smoker when drinking", "Non-smoker", "Smoker", "Trying to quit"]),
            question("workout", "Do you workout?", ["Everyday", "Often", "Sometimes", "Never"]),
            question("pets", "Pets", ["Dog", "Cat", "Reptile", "Amphibian", "Bird", "Fish", "Don’t have but love", "Other", "Turtle", "Hamster", "Rabbit", "Pet-free", "All the pets", "Want a pet"]),
            question("communication", "Communication style", ["Big time texter", "Phone caller", "Video chatter", "Bad texter", "Better in person"]),
            question("love_language", "How do you receive love?", ["Thoughtful gestures", "Presents", "Touch", "Compliments", "Time together"]),
            question("education", "Education", ["Bachelors", "In College", "High School", "PhD", "In Grad School", "Masters", "Trade School"]),
            question("zodiac", "Zodiac", ["Capricorn", "Aquarius", "Pisces", "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius"]),
            question("interests", "Interests", TINDER_INTERESTS, multiple=True, count=[2, 3]),
        ],
    },
    "pof": {
        "name": "Plenty of Fish", "color": "#00A9E0", "status": "review",
        "note": "The saved flow identifies all question screens, but option catalogs were intentionally not persisted. Use Inspect current screen while stepping through POF.",
        "questions": [
            question("first_name", "First name", kind="text"), question("birthday", "Birthday", kind="date"),
            question("gender", "Gender", ["Woman", "Man", "Non-binary"]), question("show_gender", "Show gender on profile", ["Yes", "No"]),
            question("ethnicity", "Ethnicity", ["Caucasian"], note="Only the option retained in the sanitized reviewed fixture."),
            question("seeking", "Who are you looking for?", ["Woman", "Man", "Non-binary"], multiple=True),
            question("dating_preferences", "Dating preferences", kind="live"), question("about_you", "About you", kind="live"),
            question("more_details", "More details", kind="live"), question("lifestyle", "Lifestyle", kind="live"),
            question("family", "Family", kind="live"), question("birth_order", "Birth order", kind="live"),
            question("headline", "Headline", kind="text"), question("bio", "About me", kind="textarea"),
            question("conversation_topic", "Conversation topic", kind="text"),
            question("interests", "Interests", kind="live", multiple=True),
        ],
    },
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS creators(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
      profiles_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS assets(
      id TEXT PRIMARY KEY, creator_id TEXT NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
      name TEXT NOT NULL, mime TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS accounts(
      id TEXT PRIMARY KEY, creator_id TEXT NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
      app TEXT NOT NULL, status TEXT NOT NULL, avd TEXT NOT NULL DEFAULT '', serial TEXT NOT NULL DEFAULT '',
      profile_json TEXT NOT NULL, identity_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS variants(
      id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
      asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE, kind TEXT NOT NULL,
      path TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(creators)")}
    if "profiles_json" not in columns:
        db.execute("ALTER TABLE creators ADD COLUMN profiles_json TEXT NOT NULL DEFAULT '{}'")
        db.commit()
    return db


def load_variants():
    if not VARIANTS_PATH.is_file():
        raise RuntimeError(f"variants.py not found at {VARIANTS_PATH}; set IG_VARIANTS_PATH")
    spec = importlib.util.spec_from_file_location("account_panel_variants", VARIANTS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def register_proxy_place(variants, location):
    """Make the saved proxy center available to the existing EXIF helpers."""
    label = location["label"]
    if not any(place[0] == label for place in variants.US_PLACES):
        variants.US_PLACES.append((label, float(location["latitude"]), float(location["longitude"]),
                                   location["timezone"], float(location.get("elevation") or 10)))


def identity_for(account_id, device, location):
    variants = load_variants()
    register_proxy_place(variants, location)
    rng = random.Random(int(hashlib.sha256(account_id.encode()).hexdigest()[:16], 16))
    brand = (device or {}).get("brand") or "samsung"
    name = (device or {}).get("name") or "Galaxy S25"
    identity = variants.device_identity(rng, device=(brand, name), home=location["label"])
    if name == "Galaxy S25":
        identity.update(kind="android", brand="samsung", name=name, make="samsung", model="SM-S931B", android="15")
        # Match the verified international S25 profile used by these AVDs.
        # Samsung photo Software tags use the firmware build, not a US-model
        # firmware prefix belonging to SM-S931U.
        identity["sw"] = [["2000-01-01T00:00:00+00:00", "S931BXXS4AYF1"]]
    identity["proxy_location"] = location
    return identity


def create_variants(db, account_id, creator_id, identity):
    variants = load_variants()
    register_proxy_place(variants, identity["proxy_location"])
    rows = db.execute("SELECT * FROM assets WHERE creator_id=? ORDER BY created_at", (creator_id,)).fetchall()
    target = GENERATED / account_id
    target.mkdir(parents=True, exist_ok=True)
    results = []
    for index, row in enumerate(rows, 1):
        source = Path(row["path"])
        for kind, fn in (("feed", variants.photo_variant), ("story", variants.story_image)):
            output = target / f"{index:02d}-{kind}.jpg"
            seed = int(hashlib.sha256(f"{account_id}:{row['id']}:{kind}".encode()).hexdigest()[:16], 16)
            metadata = fn(source, output, identity, random.Random(seed))
            vid = "var_" + secrets.token_hex(8)
            db.execute("INSERT INTO variants VALUES(?,?,?,?,?,?,?)",
                       (vid, account_id, row["id"], kind, str(output), json.dumps(metadata), now()))
            results.append({"id": vid, "kind": kind, "name": output.name, "metadata": metadata})
    return results


def saved_phone_profiles():
    profiles = {}
    if not PHONE_BACKUPS.is_dir():
        return profiles
    for path in PHONE_BACKUPS.glob("*/setup/proxy-location.json"):
        try:
            location = json.loads(path.read_text())
            for key in ("latitude", "longitude", "timezone", "label"):
                if not location.get(key) and location.get(key) != 0:
                    raise ValueError(key)
            avd = path.parents[1].name
            profiles[avd] = {
                "avd": avd,
                "device": {"brand": "samsung", "name": "Galaxy S25", "make": "samsung",
                           "model": "SM-S931B", "android": "15"},
                "location": {key: location[key] for key in ("latitude", "longitude", "timezone", "label")},
            }
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return profiles


def inventory():
    devices, avds = [], []
    try:
        out = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "device":
                serial = fields[0]
                avd = subprocess.run(["adb", "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"], capture_output=True, text=True, timeout=3).stdout.strip()
                devices.append({"serial": serial, "avd": avd})
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        avds = [x for x in subprocess.run(["emulator", "-list-avds"], capture_output=True, text=True, timeout=3).stdout.splitlines() if x]
    except (OSError, subprocess.SubprocessError):
        pass
    profiles = saved_phone_profiles()
    avds = sorted(set(avds) | set(profiles))
    for device in devices:
        if device["avd"] in profiles:
            device["location"] = profiles[device["avd"]]["location"]
    return devices, avds, profiles


def avd_directory(avd):
    home = Path(os.environ.get("ANDROID_AVD_HOME", Path.home() / ".android/avd"))
    directory = home / f"{avd}.avd"
    registration = home / f"{avd}.ini"
    try:
        for line in registration.read_text().splitlines():
            if line.startswith("path="):
                return Path(line[5:])
    except OSError:
        pass
    return directory


def private_read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def fleet_log_path(avd):
    folder = DATA / "fleet"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{avd}.log"


def fleet_log_tail(avd, limit=12000):
    try:
        text = fleet_log_path(avd).read_text(errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def fleet_host():
    return {"id": socket.gethostname(), "name": socket.gethostname(),
            "system": platform.system(), "scope": "local"}


def fleet_inventory():
    devices, avds, profiles = inventory()
    live = {item.get("avd"): item for item in devices if item.get("avd")}
    assigned_apps = {}
    db = None
    try:
        db = connect()
        rows = db.execute("SELECT avd,app FROM accounts WHERE avd<>'' ORDER BY updated_at DESC").fetchall()
        for row in rows:
            name = APP_SCHEMAS.get(row["app"], {}).get("name", row["app"])
            if name not in assigned_apps.setdefault(row["avd"], []):
                assigned_apps[row["avd"]].append(name)
    except sqlite3.Error:
        pass
    finally:
        if db is not None:
            db.close()
    phones = []
    for avd in sorted(set(avds) | set(profiles)):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
            continue
        setup = PHONE_BACKUPS / avd / "setup"
        certificate = private_read_json(setup / "setup-complete.json")
        location = private_read_json(setup / "proxy-location.json")
        proxy_metadata = private_read_json(setup / "nodemaven-proxy.json")
        targeting = proxy_metadata.get("targeting") or {}
        city_targeted = bool(targeting.get("city") and targeting.get("region"))
        camera = private_read_json(avd_directory(avd) / "camera/native-camera.json")
        apps = assigned_apps.get(avd) or [PACKAGE_APPS.get(package, package) for package in
                                         certificate.get("authorizedSignupPackages", [])]
        live_device = certificate.get("liveDevice") or {}
        manufacturer = str(live_device.get("manufacturer") or "Samsung").title()
        model_code = live_device.get("model") or "SM-S931B"
        model_name = "Galaxy S25" if str(model_code).startswith("SM-S93") else str(model_code)
        device = live.get(avd)
        job = FLEET_JOBS.get(avd)
        process = job.get("process") if job else None
        exit_code = process.poll() if process else None
        managed_running = bool(process and exit_code is None)
        log = fleet_log_tail(avd)
        camera_required = bool(camera.get("prepared_video"))
        runtime_ready = "Certified phone runtime restored and verified." in log
        camera_ready = "Native front Camera2 texture-motion check passed." in log
        if device and runtime_ready and (not camera_required or camera_ready):
            phase = "ready"
        elif device and runtime_ready and camera_required:
            phase = "checking-camera"
        elif device and managed_running:
            phase = "restoring"
        elif device:
            phase = "running-unmanaged"
        elif managed_running:
            phase = "starting"
        elif job and exit_code not in (None, 0):
            phase = "failed"
        else:
            phase = "stopped"
        checks = [
            {"key": "certificate", "label": "Setup certificate",
             "ok": bool(certificate.get("avd") == avd)},
            {"key": "identity", "label": "Saved device identity",
             "ok": (setup / "profile/device-profile.json").is_file()},
            {"key": "proxy", "label": "Private proxy configuration",
             "ok": (setup / "nodemaven-proxy").is_file()},
            {"key": "location", "label": "Proxy-derived location and timezone",
             "ok": all(location.get(key) is not None for key in
                       ("latitude", "longitude", "timezone"))},
            {"key": "runtime", "label": "Battery, signal and GPS runtime records",
             "ok": all((setup / path).is_file() for path in
                       ("profile/battery.conf", "profile/radio-state.json",
                        "location/location-state.json"))},
            {"key": "camera", "label": "Native camera profile",
             "ok": not camera_required or camera.get("status") == "verified_camera2_pixels",
             "optional": not camera_required},
        ]
        target_city = (targeting.get("city") or {}).get("name")
        target_region = (targeting.get("region") or {}).get("name")
        carrier = (targeting.get("isp") or {}).get("name") or proxy_metadata.get("isp")
        phones.append({
            "avd": avd, "serial": (device or {}).get("serial", ""), "phase": phase,
            "certified": bool(certificate.get("avd") == avd),
            "managed": managed_running, "exitCode": exit_code,
            "host": fleet_host(), "checks": checks, "apps": apps,
            "model": {"manufacturer": manufacturer, "name": model_name, "code": model_code},
            "location": location, "camera": {
                "configured": camera_required, "status": camera.get("status", "not-configured"),
                "fps": camera.get("fps"), "previewSize": camera.get("preview_size"),
                "sourceName": Path(camera.get("original", "")).name if camera.get("original") else None},
            "proxy": {"policy": "city-bound" if city_targeted else "legacy-exact-ip",
                      "city": target_city, "region": target_region, "carrier": carrier,
                      "rotationAllowed": city_targeted, "radiusMiles": 100 if city_targeted else None},
            "startedAt": job.get("startedAt") if job else None,
            "log": log,
        })
    return phones


def require_phone(avd):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
        raise ValueError("Invalid phone name")
    phone = next((item for item in fleet_inventory() if item["avd"] == avd), None)
    if not phone:
        raise ValueError("Phone was not found on this host")
    return phone


def launch_phone(avd):
    phone = require_phone(avd)
    if not phone["certified"]:
        raise ValueError("Phone is not certified; complete the full setup before opening it")
    if phone["phase"] not in {"stopped", "failed"}:
        raise ValueError(f"Phone is already {phone['phase'].replace('-', ' ')}")
    log_path = fleet_log_path(avd)
    stream = open(log_path, "w", encoding="utf-8")
    os.chmod(log_path, 0o600)
    stream.write(f"Managed launch started {now()} on {fleet_host()['name']}\n")
    stream.flush()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", str(REPO / "emulator_proxy.py"), "--avd", avd],
            cwd=REPO, env=env, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True)
    finally:
        stream.close()
    FLEET_JOBS[avd] = {"process": process, "startedAt": now(), "log": str(log_path)}
    return {"avd": avd, "phase": "starting", "pid": process.pid}


def stop_phone(avd):
    phone = require_phone(avd)
    if phone["serial"]:
        subprocess.run(["adb", "-s", phone["serial"], "emu", "kill"],
                       capture_output=True, text=True, timeout=15, check=True)
    else:
        job = FLEET_JOBS.get(avd)
        process = job.get("process") if job else None
        if not process or process.poll() is not None:
            raise ValueError("Phone is not running")
        os.killpg(process.pid, signal.SIGTERM)
    return {"avd": avd, "phase": "stopping"}


def verify_uploaded_video(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
        "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("The uploaded file is not a readable video")
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(data["format"]["duration"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("The uploaded video has no usable video stream")
    if width < 1 or height < 1 or not 0 < duration <= 600:
        raise ValueError("Camera videos must be between 0 and 10 minutes long")
    return {"width": width, "height": height, "duration": round(duration, 3),
            "frameRate": stream.get("avg_frame_rate")}


def replace_camera_video(avd, part):
    phone = require_phone(avd)
    if not phone["certified"]:
        raise ValueError("Phone is not certified; complete its setup before changing the camera")
    if phone["phase"] in {"starting", "restoring", "checking-camera"}:
        raise ValueError("Wait for the current phone startup to finish before changing its video")
    filename = Path(part.get_filename() or "camera-video").name
    mime = part.get_content_type()
    suffix = Path(filename).suffix.lower()
    if mime not in VIDEO_TYPES or suffix not in {".mp4", ".mov", ".webm", ".m4v"}:
        raise ValueError("Upload an MP4, MOV, M4V or WebM video")
    payload = part.get_payload(decode=True)
    if not payload:
        raise ValueError("The uploaded video is empty")
    folder = DATA / "camera-videos" / avd
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"video_{secrets.token_hex(8)}{suffix}"
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    try:
        media = verify_uploaded_video(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log_path = fleet_log_path(avd)
    stream = open(log_path, "w", encoding="utf-8")
    os.chmod(log_path, 0o600)
    stream.write(f"Camera replacement started {now()} on {fleet_host()['name']}\n")
    stream.write(f"Uploaded source: {filename} ({media['width']}×{media['height']}, {media['duration']}s)\n")
    stream.flush()
    command = [sys.executable, "-I", str(REPO / "swap_camera_video.py"),
               "--avd", avd, "--video", str(path)]
    if phone["phase"] not in {"stopped", "failed"}:
        command.append("--restart")
    try:
        process = subprocess.Popen(command, cwd=REPO,
                                   env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    finally:
        stream.close()
    FLEET_JOBS[avd] = {"process": process, "startedAt": now(), "log": str(log_path),
                       "action": "camera-replacement"}
    return {"avd": avd, "phase": "starting", "filename": filename, "media": media}


def row_json(row):
    d = dict(row)
    for key in ("profile_json", "identity_json", "metadata_json"):
        if key in d:
            d[key[:-5]] = json.loads(d.pop(key))
    if "profiles_json" in d:
        d["profiles"] = json.loads(d.pop("profiles_json") or "{}")
    return d


class Handler(SimpleHTTPRequestHandler):
    server_version = "AccountControl/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[panel] " + fmt % args + "\n")

    def auth_ok(self):
        expected = self.server.control_token
        if expected:
            return secrets.compare_digest(self.headers.get("X-Control-Token", ""), expected)
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == self.headers.get("Host")

    def json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error_json(self, status, message):
        self.json({"error": message}, status)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_UPLOAD:
            raise ValueError("Request is too large")
        return json.loads(self.rfile.read(size) or b"{}")

    def read_multipart(self, maximum=MAX_UPLOAD):
        size = int(self.headers.get("Content-Length", "0"))
        if size > maximum:
            raise ValueError(f"Upload is too large ({maximum // (1024 * 1024)} MB maximum per request)")
        raw = self.rfile.read(size)
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        return [part for part in message.iter_parts()]

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self.auth_ok():
            return self.error_json(401, "Control token required")
        if parsed.path == "/api/bootstrap":
            with connect() as db:
                creators = [row_json(r) for r in db.execute("SELECT * FROM creators ORDER BY created_at DESC")]
                for creator in creators:
                    creator["photos"] = [row_json(r) for r in db.execute("SELECT id,name,mime,sha256,created_at FROM assets WHERE creator_id=?", (creator["id"],))]
                accounts = [row_json(r) for r in db.execute("SELECT * FROM accounts ORDER BY created_at DESC")]
                for account in accounts:
                    account["variants"] = [row_json(r) for r in db.execute("SELECT id,kind,metadata_json,created_at FROM variants WHERE account_id=?", (account["id"],))]
            devices, avds, profiles = inventory()
            return self.json({"apps": APP_SCHEMAS, "creators": creators, "accounts": accounts,
                              "devices": devices, "avds": avds, "phoneProfiles": profiles,
                              "mediaPipeline": VARIANTS_PATH.is_file(),
                              "phones": fleet_inventory(), "fleetHost": fleet_host()})
        if parsed.path == "/api/phones":
            return self.json({"phones": fleet_inventory(), "host": fleet_host()})
        match = re.fullmatch(r"/api/assets/([a-zA-Z0-9_]+)", parsed.path)
        if match:
            with connect() as db:
                row = db.execute("SELECT path,mime FROM assets WHERE id=?", (match.group(1),)).fetchone()
            if not row:
                return self.error_json(404, "Photo not found")
            path = Path(row["path"]).resolve()
            uploads = UPLOADS.resolve()
            if uploads not in path.parents or not path.is_file():
                return self.error_json(404, "Photo not found")
            data = path.read_bytes()
            self.send_response(200); self.send_header("Content-Type", row["mime"])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers(); self.wfile.write(data)
            return
        match = re.fullmatch(r"/api/files/([a-zA-Z0-9_]+)", parsed.path)
        if match:
            with connect() as db:
                row = db.execute("SELECT path FROM variants WHERE id=?", (match.group(1),)).fetchone()
            if not row:
                return self.error_json(404, "File not found")
            path = Path(row["path"]).resolve()
            if GENERATED not in path.parents or not path.is_file():
                return self.error_json(404, "File not found")
            data = path.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self.auth_ok():
            return self.error_json(401, "Control token required")
        try:
            if parsed.path == "/api/creators":
                data = self.read_json(); name = str(data.get("name", "")).strip()
                if not name:
                    raise ValueError("Creator name is required")
                cid = "creator_" + secrets.token_hex(6)
                with connect() as db:
                    db.execute("INSERT INTO creators(id,name,notes,profiles_json,created_at) VALUES(?,?,?,?,?)",
                               (cid, name, str(data.get("notes", "")), "{}", now()))
                    db.commit()
                return self.json({"id": cid, "name": name}, 201)
            match = re.fullmatch(r"/api/creators/([a-zA-Z0-9_]+)/photos", parsed.path)
            if match:
                cid = match.group(1); saved = []
                with connect() as db:
                    if not db.execute("SELECT 1 FROM creators WHERE id=?", (cid,)).fetchone():
                        return self.error_json(404, "Creator not found")
                    for part in self.read_multipart():
                        if part.get_content_disposition() != "form-data" or not part.get_filename():
                            continue
                        mime = part.get_content_type(); payload = part.get_payload(decode=True)
                        if mime not in IMAGE_TYPES or not payload:
                            continue
                        aid = "asset_" + secrets.token_hex(8); folder = UPLOADS / cid; folder.mkdir(parents=True, exist_ok=True)
                        path = folder / f"{aid}{IMAGE_TYPES[mime]}"; path.write_bytes(payload)
                        digest = hashlib.sha256(payload).hexdigest()
                        db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)", (aid, cid, Path(part.get_filename()).name, mime, str(path), digest, now()))
                        saved.append({"id": aid, "name": Path(part.get_filename()).name, "sha256": digest})
                    db.commit()
                if not saved:
                    raise ValueError("No supported image was uploaded")
                return self.json({"photos": saved}, 201)
            if parsed.path == "/api/accounts":
                data = self.read_json(); cid = data.get("creatorId"); apps = data.get("apps") or []
                if not cid or not apps:
                    raise ValueError("Choose a creator and at least one app")
                avd = str(data.get("avd", ""))
                profiles = saved_phone_profiles()
                phone = profiles.get(avd)
                if not phone:
                    raise ValueError("Choose a phone with a verified saved proxy location")
                serial = str(data.get("serial", ""))
                if serial:
                    connected, _, _ = inventory()
                    live = next((item for item in connected if item["serial"] == serial), None)
                    if not live or live["avd"] != avd:
                        raise ValueError("Connected emulator does not match the selected phone")
                made = []
                with connect() as db:
                    if not db.execute("SELECT 1 FROM creators WHERE id=?", (cid,)).fetchone():
                        raise ValueError("Creator not found")
                    if not db.execute("SELECT 1 FROM assets WHERE creator_id=?", (cid,)).fetchone():
                        raise ValueError("Upload creator photos before preparing accounts")
                    for app in apps:
                        if app not in APP_SCHEMAS:
                            raise ValueError(f"Unsupported app: {app}")
                        account_id = "acc_" + secrets.token_hex(7)
                        profile = (data.get("profiles") or {}).get(app, {})
                        identity = identity_for(account_id, phone["device"], phone["location"])
                        stamp = now()
                        db.execute("INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (account_id, cid, app, "prepared", avd, serial, json.dumps(profile), json.dumps(identity), stamp, stamp))
                        generated = create_variants(db, account_id, cid, identity)
                        made.append({"id": account_id, "app": app, "identity": identity, "variants": generated})
                    db.commit()
                return self.json({"accounts": made}, 201)
            if parsed.path == "/api/discover":
                data = self.read_json(); serial = re.fullmatch(r"[A-Za-z0-9._:-]+", str(data.get("serial", "")))
                if not serial:
                    raise ValueError("A valid connected emulator serial is required")
                serial = serial.group(0)
                subprocess.run(["adb", "-s", serial, "shell", "uiautomator", "dump", "/sdcard/account-panel.xml"], capture_output=True, timeout=10, check=True)
                xml = subprocess.run(["adb", "-s", serial, "exec-out", "cat", "/sdcard/account-panel.xml"], capture_output=True, timeout=10, check=True).stdout
                root = ET.fromstring(xml)
                labels = []
                for node in root.iter("node"):
                    value = (node.get("text") or node.get("content-desc") or "").strip()
                    if value and len(value) <= 120 and (node.get("clickable") == "true" or node.get("checkable") == "true") and value not in labels:
                        labels.append(value)
                return self.json({"labels": labels, "capturedAt": now()})
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/(launch|stop)", parsed.path)
            if match:
                avd, action = match.groups()
                result = launch_phone(avd) if action == "launch" else stop_phone(avd)
                return self.json(result, 202)
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/camera-video", parsed.path)
            if match:
                parts = [part for part in self.read_multipart(MAX_VIDEO_UPLOAD)
                         if part.get_content_disposition() == "form-data" and part.get_filename()]
                if len(parts) != 1:
                    raise ValueError("Upload exactly one camera video")
                return self.json(replace_camera_video(match.group(1), parts[0]), 202)
            return self.error_json(404, "Unknown API route")
        except (ValueError, json.JSONDecodeError) as exc:
            return self.error_json(400, str(exc))
        except subprocess.CalledProcessError:
            return self.error_json(409, "The requested emulator operation failed")
        except Exception as exc:
            self.log_error("%s", exc)
            return self.error_json(500, str(exc))

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if not self.auth_ok():
            return self.error_json(401, "Control token required")
        try:
            match = re.fullmatch(r"/api/creators/([a-zA-Z0-9_]+)", parsed.path)
            if not match:
                return self.error_json(404, "Unknown API route")
            data = self.read_json()
            name = str(data.get("name", "")).strip()
            if not name:
                raise ValueError("Creator name is required")
            profiles = data.get("profiles") or {}
            if not isinstance(profiles, dict) or any(
                    app not in APP_SCHEMAS or not isinstance(values, dict)
                    for app, values in profiles.items()):
                raise ValueError("Creator profile answers are invalid")
            with connect() as db:
                result = db.execute(
                    "UPDATE creators SET name=?,notes=?,profiles_json=? WHERE id=?",
                    (name, str(data.get("notes", "")), json.dumps(profiles), match.group(1)))
                if not result.rowcount:
                    return self.error_json(404, "Creator not found")
                db.commit()
            return self.json({"id": match.group(1), "name": name, "profiles": profiles})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.error_json(400, str(exc))
        except Exception as exc:
            self.log_error("%s", exc)
            return self.error_json(500, str(exc))

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not self.auth_ok():
            return self.error_json(401, "Control token required")
        match = re.fullmatch(
            r"/api/creators/([a-zA-Z0-9_]+)/photos/([a-zA-Z0-9_]+)", parsed.path)
        if not match:
            return self.error_json(404, "Unknown API route")
        cid, aid = match.groups()
        try:
            with connect() as db:
                row = db.execute(
                    "SELECT path FROM assets WHERE id=? AND creator_id=?", (aid, cid)).fetchone()
                if not row:
                    return self.error_json(404, "Photo not found")
                if db.execute("SELECT 1 FROM variants WHERE asset_id=? LIMIT 1", (aid,)).fetchone():
                    return self.error_json(
                        409, "This photo is already part of a prepared account and cannot be removed")
                db.execute("DELETE FROM assets WHERE id=? AND creator_id=?", (aid, cid))
                db.commit()
            path = Path(row["path"]).resolve()
            if UPLOADS.resolve() in path.parents:
                path.unlink(missing_ok=True)
            return self.json({"deleted": aid})
        except Exception as exc:
            self.log_error("%s", exc)
            return self.error_json(500, str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    token = os.environ.get("CONTROL_PANEL_TOKEN", "")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise SystemExit("CONTROL_PANEL_TOKEN is required when binding beyond localhost")
    connect().close()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.control_token = token
    print(f"Creator Control is ready at http://{args.host}:{args.port}", flush=True)
    if token:
        print("API access is protected by CONTROL_PANEL_TOKEN.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
