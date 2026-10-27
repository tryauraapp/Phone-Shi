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
import hmac
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
from urllib.parse import parse_qs, quote, unquote, urlparse
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
NODEMAVEN_KEY = DATA / "secrets" / "nodemaven-api-key"
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
               "video/x-m4v": ".m4v", "application/octet-stream": ""}
PACKAGE_APPS = {
    "com.bumble.app": "Bumble", "com.tinder": "Tinder",
    "com.pof.android": "Plenty of Fish", "co.hinge.app": "Hinge",
    "com.okcupid.okcupid": "OkCupid", "com.match.android.matchmobile": "Match.com",
    "com.eharmony": "eHarmony", "io.cmbus.app": "Coffee Meets Bagel",
    "com.facebook.katana": "Facebook Dating", "co.feeld": "Feeld",
    "com.zoosk.zoosk": "Zoosk", "com.badoo.mobile": "Badoo",
    "com.elitesingles.dating": "EliteSingles", "com.hily.app": "Hily",
    "com.ftw_and_co.happn": "Happn",
}
FLEET_JOBS = {}
SHARE_TTL_SECONDS = int(os.environ.get("PHONE_SHI_SHARE_TTL_SECONDS", "86400"))


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


def starter_schema(name, color, note=""):
    """Profile storage for apps whose live onboarding is not yet reviewed."""
    return {
        "name": name, "color": color, "status": "review",
        "note": note or (
            "Starter fields only. Inspect the live onboarding before recording exact choices; "
            "randomization is limited to reviewed, non-identity options."),
        "questions": [
            question("first_name", "First name", kind="text"),
            question("birthday", "Birthday", kind="date"),
            question("gender", "Gender", kind="live"),
            question("show_gender", "Show gender on profile", ["Yes", "No"]),
            question("relationship_goal", "Relationship goal", kind="live"),
            question("height", "Height", kind="live"),
            question("interests", "Interests", kind="live", multiple=True),
            question("bio", "About me", kind="textarea"),
        ],
    }


APP_SCHEMAS.update({
    "hinge": starter_schema("Hinge", "#7D56F4"),
    "okcupid": starter_schema("OkCupid", "#246BFE"),
    "match": starter_schema("Match.com", "#1676D2"),
    "eharmony": starter_schema("eHarmony", "#6E44FF"),
    "coffee-meets-bagel": starter_schema("Coffee Meets Bagel", "#D97745"),
    "facebook-dating": starter_schema(
        "Facebook Dating", "#1877F2",
        "Facebook Dating is inside the Facebook app. Facebook login and opening Dating are "
        "manual checkpoints before its onboarding can be reviewed."),
    "feeld": starter_schema("Feeld", "#D95C4F"),
    "zoosk": starter_schema("Zoosk", "#36A9E1"),
    "badoo": starter_schema("Badoo", "#783BF9"),
    "elitesingles": starter_schema("EliteSingles", "#8E744D"),
    "hily": starter_schema("Hily", "#A94CFF"),
    "happn": starter_schema("Happn", "#00AFC7"),
})


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode_phone_share(avd, secret, *, expires=None):
    """Create an expiring, phone-scoped bearer token for the browser viewer."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
        raise ValueError("Invalid phone name")
    expiry = int(expires if expires is not None else
                 datetime.now(timezone.utc).timestamp() + SHARE_TTL_SECONDS)
    payload = json.dumps(
        {"a": avd, "e": expiry}, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).digest()
    return encoded + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def decode_phone_share(token, secret, *, timestamp=None):
    """Validate a phone share token and return its AVD and expiry."""
    try:
        encoded, supplied = token.split(".", 1)
        expected = hmac.new(secret, encoded.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)))
        avd, expiry = str(payload["a"]), int(payload["e"])
        if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
            raise ValueError
        current = int(timestamp if timestamp is not None else
                      datetime.now(timezone.utc).timestamp())
        if expiry < current:
            raise ValueError
        return {"avd": avd, "expires": expiry}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def safe_share_base(value):
    """Accept only a bare HTTP(S) origin for generated links."""
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or
            parsed.username or parsed.password):
        return ""
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return ""
    return value


def sanitize_ui_xml(payload):
    """Remove values typed into Android text fields before persisting a fixture."""
    root = ET.fromstring(payload)
    for node in root.iter("node"):
        if node.get("password") == "true" or node.get("class", "").endswith("EditText"):
            if node.get("text"):
                node.set("text", "[redacted]")
            if node.get("content-desc"):
                node.set("content-desc", "[redacted]")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def record_phone_screen(avd, app):
    if app not in APP_SCHEMAS:
        raise ValueError("Choose the app being reviewed")
    device = next((item for item in inventory()[0] if item.get("avd") == avd), None)
    if not device:
        raise ValueError("Phone is not running")
    serial = device["serial"]
    subprocess.run(
        ["adb", "-s", serial, "shell", "uiautomator", "dump", "--compressed",
         "/sdcard/account-panel-record.xml"], capture_output=True, timeout=15, check=True)
    xml = subprocess.run(
        ["adb", "-s", serial, "exec-out", "cat", "/sdcard/account-panel-record.xml"],
        capture_output=True, timeout=12, check=True).stdout
    cleaned = sanitize_ui_xml(xml)
    root = ET.fromstring(cleaned)
    packages = [node.get("package") for node in root.iter("node") if node.get("package")]
    package = max(set(packages), key=packages.count) if packages else "unknown"
    labels = []
    for node in root.iter("node"):
        value = (node.get("text") or node.get("content-desc") or "").strip()
        if (value and value != "[redacted]" and len(value) <= 160 and
                (node.get("clickable") == "true" or node.get("checkable") == "true") and
                value not in labels):
            labels.append(value)
    focus = subprocess.run(
        ["adb", "-s", serial, "shell", "dumpsys", "window", "windows"],
        capture_output=True, text=True, timeout=12, check=True).stdout
    match = re.search(r"mCurrentFocus=.*? ([A-Za-z0-9._]+/[A-Za-z0-9._$]+)", focus)
    activity = match.group(1) if match else "unknown"
    fingerprint = hashlib.sha256(cleaned).hexdigest()[:16]
    folder = DATA / "screen-recordings" / app / avd
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    existing = next(folder.glob(f"*-{fingerprint}.json"), None)
    if existing:
        return {**json.loads(existing.read_text()), "duplicate": True}
    screenshot = subprocess.run(
        ["adb", "-s", serial, "exec-out", "screencap", "-p"],
        capture_output=True, timeout=12, check=True).stdout
    if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Phone screenshot was unavailable")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = folder / f"{stamp}-{fingerprint}"
    base.with_suffix(".xml").write_bytes(cleaned)
    base.with_suffix(".png").write_bytes(screenshot)
    record = {
        "app": app, "avd": avd, "serial": serial, "package": package,
        "activity": activity, "fingerprint": fingerprint, "labels": labels,
        "capturedAt": now(), "duplicate": False,
    }
    base.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    for path in (base.with_suffix(".xml"), base.with_suffix(".png"), base.with_suffix(".json")):
        os.chmod(path, 0o600)
    return record


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
            saved_device = private_read_json(path.parent / "profile/device-profile.json")
            samsung = str(saved_device.get("model", "")).startswith("SM-S93")
            profiles[avd] = {
                "avd": avd,
                "device": {
                    "brand": ("samsung" if samsung else
                              str(saved_device.get("manufacturer") or "Android").lower()),
                    "name": "Galaxy S25" if samsung else str(
                        saved_device.get("model") or "VPS phone"),
                    "make": ("samsung" if samsung else
                             str(saved_device.get("manufacturer") or "Android")),
                    "model": saved_device.get("model") or "VPS phone",
                    "android": saved_device.get("android") or "15",
                },
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
    chunks = []
    worker = DATA / "provisioning" / avd / "worker.log"
    try:
        chunks.append(worker.read_text(errors="replace"))
    except OSError:
        pass
    try:
        chunks.append(fleet_log_path(avd).read_text(errors="replace"))
    except OSError:
        pass
    return "\n".join(chunks)[-limit:]


def provisioning_record(avd):
    folder = DATA / "provisioning" / avd
    return private_read_json(folder / "status.json"), private_read_json(folder / "request.json")


def provisioning_names():
    root = DATA / "provisioning"
    if not root.is_dir():
        return set()
    return {path.name for path in root.iterdir()
            if path.is_dir() and re.fullmatch(r"[A-Za-z0-9._-]+", path.name)}


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
    for avd in sorted(set(avds) | set(profiles) | provisioning_names()):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
            continue
        setup = PHONE_BACKUPS / avd / "setup"
        certificate = private_read_json(setup / "setup-complete.json")
        provisioning, provision_request = provisioning_record(avd)
        location = private_read_json(setup / "proxy-location.json")
        proxy_metadata = private_read_json(setup / "nodemaven-proxy.json")
        targeting = proxy_metadata.get("targeting") or {}
        city_targeted = bool(targeting.get("city") and targeting.get("region"))
        camera = private_read_json(avd_directory(avd) / "camera/native-camera.json")
        apps = assigned_apps.get(avd) or [PACKAGE_APPS.get(package, package) for package in
                                         certificate.get("authorizedSignupPackages", [])]
        if not apps and provision_request.get("app") in APP_SCHEMAS:
            apps = [APP_SCHEMAS[provision_request["app"]]["name"]]
        live_device = certificate.get("liveDevice") or {}
        saved_device = private_read_json(setup / "profile/device-profile.json")
        manufacturer = str(live_device.get("manufacturer") or
                           saved_device.get("manufacturer") or "Android").title()
        model_code = live_device.get("model") or saved_device.get("model") or "VPS phone"
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
        provisioning_phase = provisioning.get("phase")
        if provisioning_phase == "ready" and device:
            phase = "ready"
        elif provisioning_phase == "failed" and device:
            phase = "running-unmanaged"
        elif provisioning_phase and provisioning_phase not in {"ready"}:
            phase = provisioning_phase
        elif device and runtime_ready and (not camera_required or camera_ready):
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
        certificate_ok = (certificate.get("avd") == avd and
                          certificate.get("schema") in {None, 1, 2})
        checks = [
            {"key": "certificate", "label": "Setup certificate",
             "ok": bool(certificate_ok)},
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
            "certified": bool(certificate_ok),
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
            "provisioning": {
                "stage": provisioning.get("stage"),
                "progress": provisioning.get("progress"),
                "message": provisioning.get("message"),
                "updatedAt": provisioning.get("updatedAt"),
            } if provisioning else None,
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


def phone_creation_capabilities():
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT", "/opt/android-sdk"))
    return {
        "supported": (platform.system() == "Linux" and platform.machine().lower() in
                      {"x86_64", "amd64"} and Path("/dev/kvm").exists()),
        "host": f"{platform.system()} {platform.machine()}",
        "proxyConfigured": NODEMAVEN_KEY.is_file(),
        "systemImage": (sdk / "system-images/android-35/google_apis_playstore/x86_64/system.img").is_file(),
        "defaultRam": 2048,
        "defaultCores": 4,
    }


def multipart_fields(parts):
    fields, files = {}, {}
    for part in parts:
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        if part.get_filename():
            files[name] = part
        else:
            fields[name] = str(part.get_content()).strip()
    return fields, files


def save_nodemaven_key(value):
    value = str(value or "").strip()
    if not value:
        return
    if any(character.isspace() for character in value) or len(value) < 24:
        raise ValueError("NodeMaven API key is invalid")
    NODEMAVEN_KEY.parent.mkdir(parents=True, exist_ok=True)
    temporary = NODEMAVEN_KEY.with_name(NODEMAVEN_KEY.name + "." + secrets.token_hex(4))
    temporary.write_text(value + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, NODEMAVEN_KEY)


def start_phone_worker(avd, command, action):
    folder = DATA / "provisioning" / avd
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "worker.log"
    stream = open(log_path, "a", encoding="utf-8")
    os.chmod(log_path, 0o600)
    stream.write(f"\n{action} requested {now()} on {fleet_host()['name']}\n")
    stream.flush()
    try:
        process = subprocess.Popen(
            command, cwd=REPO, env=dict(os.environ, PYTHONUNBUFFERED="1"),
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        stream.close()
    FLEET_JOBS[avd] = {
        "process": process, "startedAt": now(), "log": str(log_path), "action": action}
    return process


def create_phone(parts):
    capabilities = phone_creation_capabilities()
    if not capabilities["supported"] or not capabilities["systemImage"]:
        raise ValueError("This host is not ready for Linux x86-64 KVM phone creation")
    fields, files = multipart_fields(parts)
    app = fields.get("app", "")
    if app not in APP_SCHEMAS:
        raise ValueError("Choose a supported app")
    region, city = fields.get("region", "").strip(), fields.get("city", "").strip()
    if not region or not city or len(region) > 80 or len(city) > 80:
        raise ValueError("Enter an exact US state and city")
    name = fields.get("name", "").strip() or \
        f"VPS_Phone_{datetime.now(timezone.utc):%Y%m%d}_{secrets.token_hex(4)}"
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", name):
        raise ValueError("Phone name must use 3–64 letters, numbers, dots, underscores or dashes")
    if name in set(inventory()[1]) | provisioning_names():
        raise ValueError("A phone or provisioning job already uses this name")
    try:
        ram, cores = int(fields.get("ram", "2048")), int(fields.get("cores", "4"))
    except ValueError as exc:
        raise ValueError("RAM and CPU values must be numbers") from exc
    if not 1536 <= ram <= 4096 or not 2 <= cores <= 8:
        raise ValueError("Use 1536–4096 MB RAM and 2–8 CPU cores")
    save_nodemaven_key(fields.get("proxyApiKey"))
    if not NODEMAVEN_KEY.is_file():
        raise ValueError("Enter the NodeMaven API key for the first VPS phone")
    video = files.get("cameraVideo")
    if not video:
        raise ValueError("Upload this phone’s camera video")
    filename = Path(video.get_filename() or "camera-video").name
    suffix = Path(filename).suffix.lower()
    if video.get_content_type() not in VIDEO_TYPES or suffix not in {
            ".mp4", ".mov", ".webm", ".m4v"}:
        raise ValueError("Camera video must be MP4, MOV, M4V or WebM")
    payload = video.get_payload(decode=True)
    if not payload:
        raise ValueError("Camera video is empty")
    folder = DATA / "provisioning" / name
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / f"camera-source{suffix}"
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    try:
        verify_uploaded_video(path)
        status_path = folder / "status.json"
        status_path.write_text(json.dumps({
            "avd": name, "phase": "queued", "stage": "queued", "progress": 1,
            "message": "Waiting for the VPS provisioning worker", "updatedAt": now(),
        }, indent=2) + "\n")
        os.chmod(status_path, 0o600)
        command = [
            sys.executable, "-I", str(REPO / "provision_vps_phone.py"),
            "--avd", name, "--data", str(DATA), "--app", app,
            "--region", region, "--city", city, "--ram", str(ram),
            "--cores", str(cores), "--camera-video", str(path),
            "--proxy-key", str(NODEMAVEN_KEY),
        ]
        process = start_phone_worker(name, command, "phone-provisioning")
    except Exception:
        path.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
        raise
    return {"avd": name, "phase": "queued", "pid": process.pid}


def resume_phone_setup(avd):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", avd):
        raise ValueError("Invalid phone name")
    status, request = provisioning_record(avd)
    if not request:
        raise ValueError("No VPS provisioning record exists for this phone")
    if status.get("phase") != "manual-required":
        raise ValueError("This phone is not waiting for setup verification")
    command = [
        sys.executable, "-I", str(REPO / "provision_vps_phone.py"),
        "--avd", avd, "--data", str(DATA), "--resume",
    ]
    process = start_phone_worker(avd, command, "phone-setup-resume")
    return {"avd": avd, "phase": "checking", "pid": process.pid}


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

    def phone_share(self, token):
        return decode_phone_share(token, self.server.share_secret)

    def share_url(self, token, requested_base=""):
        base = self.server.share_base_url or safe_share_base(requested_base)
        if not base:
            proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip()
            if proto not in {"http", "https"}:
                proto = "http"
            base = f"{proto}://{self.headers.get('Host', '127.0.0.1:8790')}"
        return f"{base}/phone/{quote(token, safe='.')}"

    def phone_device(self, avd):
        return next((item for item in inventory()[0] if item.get("avd") == avd), None)

    def send_file(self, path, content_type, *, cache="no-store"):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def send_phone_screen(self, avd):
        device = self.phone_device(avd)
        if not device:
            return self.error_json(404, "Phone is not running")
        result = subprocess.run(
            ["adb", "-s", device["serial"], "exec-out", "screencap", "-p"],
            capture_output=True, timeout=12, check=True)
        if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            return self.error_json(409, "Phone screen capture was unavailable")
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(result.stdout)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(result.stdout)

    def apply_phone_input(self, avd, data):
        device = self.phone_device(avd)
        if not device:
            raise ValueError("Phone is not running")
        action = data.get("action")
        if action == "tap":
            x, y = int(data.get("x", -1)), int(data.get("y", -1))
            if not 0 <= x <= 4096 or not 0 <= y <= 4096:
                raise ValueError("Tap coordinates are outside the phone screen")
            command = ["adb", "-s", device["serial"], "shell", "input", "tap",
                       str(x), str(y)]
        elif action == "swipe":
            points = [int(data.get(key, -1)) for key in ("x1", "y1", "x2", "y2")]
            duration = max(80, min(1500, int(data.get("duration", 300))))
            if any(value < 0 or value > 4096 for value in points):
                raise ValueError("Swipe coordinates are outside the phone screen")
            command = ["adb", "-s", device["serial"], "shell", "input", "swipe",
                       *(str(value) for value in points), str(duration)]
        elif action in {"back", "home", "recent"}:
            key = {"back": "4", "home": "3", "recent": "187"}[action]
            command = ["adb", "-s", device["serial"], "shell", "input", "keyevent", key]
        else:
            raise ValueError("Unsupported phone input")
        subprocess.run(command, capture_output=True, timeout=10, check=True)
        return {"avd": avd, "action": action}

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
        share_page = re.fullmatch(r"/phone/([A-Za-z0-9._-]+)", parsed.path)
        if share_page:
            if not self.phone_share(share_page.group(1)):
                return self.error_json(403, "This phone link is invalid or has expired")
            return self.send_file(DIST / "phone.html", "text/html; charset=utf-8")
        share_screen = re.fullmatch(r"/phone/([A-Za-z0-9._-]+)/screen\.png", parsed.path)
        if share_screen:
            share = self.phone_share(share_screen.group(1))
            if not share:
                return self.error_json(403, "This phone link is invalid or has expired")
            return self.send_phone_screen(share["avd"])
        share_qr = re.fullmatch(r"/phone/([A-Za-z0-9._-]+)/qr\.svg", parsed.path)
        if share_qr:
            token = share_qr.group(1)
            if not self.phone_share(token):
                return self.error_json(403, "This phone link is invalid or has expired")
            base = parse_qs(parsed.query).get("base", [""])[0]
            target = self.share_url(token, base)
            result = subprocess.run(
                ["qrencode", "-t", "SVG", "-m", "1", "-o", "-", target],
                capture_output=True, timeout=8, check=True)
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(result.stdout)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            self.wfile.write(result.stdout)
            return
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
                              "phones": fleet_inventory(), "fleetHost": fleet_host(),
                              "phoneCreation": phone_creation_capabilities()})
        if parsed.path == "/api/phones":
            return self.json({"phones": fleet_inventory(), "host": fleet_host()})
        match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/screen\.png", parsed.path)
        if match:
            return self.send_phone_screen(match.group(1))
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
        share_input = re.fullmatch(r"/phone/([A-Za-z0-9._-]+)/input", parsed.path)
        if share_input:
            share = self.phone_share(share_input.group(1))
            if not share:
                return self.error_json(403, "This phone link is invalid or has expired")
            try:
                return self.json(self.apply_phone_input(share["avd"], self.read_json()))
            except (ValueError, json.JSONDecodeError) as exc:
                return self.error_json(400, str(exc))
            except subprocess.CalledProcessError:
                return self.error_json(409, "The requested emulator operation failed")
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
            if parsed.path == "/api/phones":
                return self.json(create_phone(self.read_multipart(MAX_VIDEO_UPLOAD)), 202)
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
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/input", parsed.path)
            if match:
                return self.json(self.apply_phone_input(match.group(1), self.read_json()))
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/share", parsed.path)
            if match:
                avd = match.group(1)
                if not self.phone_device(avd):
                    raise ValueError("Start the phone before creating a browser link")
                data = self.read_json()
                token = encode_phone_share(avd, self.server.share_secret)
                url = self.share_url(token, data.get("baseUrl", ""))
                parsed_url = urlparse(url)
                portable = parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
                expires = decode_phone_share(token, self.server.share_secret)["expires"]
                qr_base = url.rsplit("/phone/", 1)[0]
                return self.json({
                    "avd": avd,
                    "url": url,
                    "qr": f"/phone/{token}/qr.svg?base={quote(qr_base, safe='')}",
                    "expires": datetime.fromtimestamp(
                        expires, timezone.utc).isoformat(timespec="seconds"),
                    "portable": portable,
                }, 201)
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/record-screen", parsed.path)
            if match:
                data = self.read_json()
                return self.json(record_phone_screen(
                    match.group(1), str(data.get("app", ""))), 201)
            match = re.fullmatch(r"/api/phones/([A-Za-z0-9._-]+)/resume-setup", parsed.path)
            if match:
                return self.json(resume_phone_setup(match.group(1)), 202)
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
    server.share_secret = hashlib.sha256(
        (token or secrets.token_hex(32)).encode("utf-8")).digest()
    server.share_base_url = safe_share_base(
        os.environ.get("PHONE_SHI_SHARE_BASE_URL", ""))
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
