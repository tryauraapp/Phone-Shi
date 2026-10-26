"""Reel files and the per-post variant ("the metadata thing").

Ported from the Facebook pages tool (facebook_tool/posting.py, 2026-10-09) for Instagram accounts on GeeLark phones:
every post gets its own file. A reel's capture record (where, when, on which iPhone it was "filmed") is made once per
reel and model and shared by every account that posts it; the edit (a 1-3 % crop at a random spot, a slight colour
change, the sound a little louder or quieter) is different for every post. The output is an .mp4 (GeeLark takes mp4
and webm only) with every original tag dropped and iPhone QuickTime tags written in.
"""
from __future__ import annotations

import os
import asyncio
import hashlib
import json
import logging
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("instagram_tool.variants")

US_PLACES = [("Los Angeles, CA", 34.0522, -118.2437, "America/Los_Angeles", 90), ("Miami, FL", 25.7700, -80.2100, "America/New_York", 3),
             ("Austin, TX", 30.2672, -97.7431, "America/Chicago", 150), ("Scottsdale, AZ", 33.4942, -111.9261, "America/Phoenix", 380),
             ("Nashville, TN", 36.1627, -86.7816, "America/Chicago", 170), ("Las Vegas, NV", 36.1699, -115.1398, "America/Los_Angeles", 610),
             ("San Diego, CA", 32.7480, -117.1300, "America/Los_Angeles", 90), ("Orlando, FL", 28.5383, -81.3792, "America/New_York", 30),
             ("Dallas, TX", 32.7767, -96.7970, "America/Chicago", 140), ("Atlanta, GA", 33.7490, -84.3880, "America/New_York", 320),
             ("Denver, CO", 39.7392, -104.9903, "America/Denver", 1610), ("Tampa, FL", 27.9600, -82.4800, "America/New_York", 15),
             ("Charlotte, NC", 35.2271, -80.8431, "America/New_York", 230), ("Phoenix, AZ", 33.4484, -112.0740, "America/Phoenix", 340),
             ("Houston, TX", 29.7604, -95.3698, "America/Chicago", 15)]
IPHONES = ["iPhone 15 Pro", "iPhone 15 Pro Max", "iPhone 16 Pro", "iPhone 16 Pro Max"]
IOS_VERSIONS = ["26.0.1", "26.1", "26.2", "26.3", "26.4", "26.5"]          # oldest first: a phone only ever moves up
# The Android phones GeeLark gives us (Luca, 2026-10-17: the file's metadata has to match the phone it is posted
# from, "so not iPhone"): marketing name -> (EXIF Make, EXIF Model = the US model code, back camera (focal mm,
# f-number, 35 mm equivalent), front camera). Anything not listed gets a generic entry built from GeeLark's brand
# and model strings.
ANDROID_PHONES = {
    "Galaxy S25": ("samsung", "SM-S931B", (6.3, 1.8, 24), (3.3, 2.2, 26)),
    "Galaxy S24": ("samsung", "SM-S921U", (6.3, 1.8, 24), (3.3, 2.2, 26)), "Galaxy S24+": ("samsung", "SM-S926U", (6.3, 1.8, 24), (3.3, 2.2, 26)),
    "Galaxy S23": ("samsung", "SM-S911U", (6.3, 1.8, 24), (3.3, 2.2, 26)), "Galaxy S23 FE": ("samsung", "SM-S711U", (5.4, 1.8, 24), (3.3, 2.2, 26)),
    "Galaxy S22": ("samsung", "SM-S901U", (5.4, 1.8, 23), (3.3, 2.2, 26)), "Galaxy S21 FE 5G": ("samsung", "SM-G990U", (5.4, 1.8, 26), (3.3, 2.2, 26)),
    "Galaxy A15 5G": ("samsung", "SM-A156U", (5.2, 1.8, 26), (3.3, 2.2, 26)), "Galaxy A15": ("samsung", "SM-A155M", (5.2, 1.8, 26), (3.3, 2.2, 26)),
    "Galaxy A54 5G": ("samsung", "SM-A546U", (5.4, 1.8, 26), (3.3, 2.2, 26)), "Galaxy C55 5G": ("samsung", "SM-C5560", (5.4, 1.8, 26), (3.3, 2.2, 26)),
    "Pixel 8 Pro": ("Google", "Pixel 8 Pro", (6.9, 1.68, 24), (2.7, 2.2, 20)), "Pixel 8a": ("Google", "Pixel 8a", (4.8, 1.89, 26), (2.7, 2.2, 20)),
    "Pixel 7": ("Google", "Pixel 7", (6.81, 1.85, 24), (2.7, 2.2, 20)),
}
# Software strings a phone reports in its photos: Samsung writes the firmware build, the rest the Android build id.
# Oldest first, like IOS_VERSIONS; the model code's first four letters start a Samsung build (S921U -> S921USQ…).
SAMSUNG_BUILDS = ["{m}SQU1AXAB", "{m}SQS2AXD3", "{m}SQU3AXG5", "{m}SQS4AXJ1", "{m}SQU5AXK3"]
ANDROID_BUILDS = ["UP1A.231005.007", "UQ1A.240105.004", "UQ1A.240205.002", "AP1A.240405.002", "AP2A.240705.005"]
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}


def utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------- identity and records
def device_identity(rng: random.Random, saved: dict | None = None, device: tuple[str, str] | None = None, home: str | None = None) -> dict:
    """One phone's identity: its make and model, a home city and its software history ([since, version]).
    ``device`` = (brand, model) as GeeLark reports the phone gives an Android identity matching that phone; without
    it the old iPhone identity is made. ``home`` keeps a city already chosen for the account."""
    if saved:
        return saved
    home = home or rng.choice(US_PLACES)[0]
    if device is None:
        return {"model": rng.choice(IPHONES), "home": home, "ios": [["2000-01-01T00:00:00+00:00", rng.choice(IOS_VERSIONS[1:4])]]}
    brand, name = (device[0] or "").strip(), (device[1] or "").strip()
    make, code, back, front = ANDROID_PHONES.get(name, (brand or "Android", name or "Android phone", (5.5, 1.8, 26), (3.0, 2.2, 26)))
    builds = _builds(make, code)
    return {"kind": "android", "brand": brand or make, "name": name or code, "make": make, "model": code, "android": "14",
            "home": home, "sw": [["2000-01-01T00:00:00+00:00", rng.choice(builds[1:4])]]}


def _builds(make: str, code: str) -> list[str]:
    if make == "samsung":
        return [b.format(m=code.replace("SM-", "")) for b in SAMSUNG_BUILDS]
    return list(ANDROID_BUILDS)


def _history(identity: dict) -> tuple[list, list[str]]:
    """(the software history list, the ordered versions it can move through)."""
    if identity.get("kind") == "android":
        return identity.setdefault("sw", [["2000-01-01T00:00:00+00:00", ANDROID_BUILDS[1]]]), _builds(identity.get("make", ""), identity.get("model", ""))
    return identity["ios"], IOS_VERSIONS


def is_android(identity: dict) -> bool:
    return identity.get("kind") == "android"


def ios_at(identity: dict, when: datetime) -> str:
    """The software version the phone had at ``when`` (iOS version, or the Android build/firmware string)."""
    hist, _ = _history(identity)
    version = hist[0][1]
    for since, v in hist:
        if utc(since) <= when:
            version = v
    return version


def maybe_update_ios(rng: random.Random, identity: dict, when: datetime) -> None:
    """Every month or so the phone takes its next software update (never a downgrade, never past the newest we know)."""
    hist, versions = _history(identity)
    since, current = hist[-1]
    if current in versions and versions.index(current) < len(versions) - 1 \
            and (when - utc(since)).days >= 30 and rng.random() < 0.3:
        hist.append([iso(when), versions[versions.index(current) + 1]])


def capture_record(rng: random.Random, when: datetime, identity: dict) -> dict:
    """Where, when and on what one reel was "taken": filmed 1-21 days before ``when``, in the daytime, in the model's
    home city, on her phone with the iOS she had then. Made once per reel and shared by every account."""
    name, lat, lon, tzname, elev = next(p for p in US_PLACES if p[0] == identity["home"])
    tz = ZoneInfo(tzname)
    day = (when - timedelta(days=rng.randint(1, 21))).astimezone(tz)
    filmed = day.replace(hour=rng.randint(9, 19), minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
    lat, lon = round(lat + rng.uniform(-0.012, 0.012), 4), round(lon + rng.uniform(-0.012, 0.012), 4)
    alt = round(max(1.0, elev + rng.uniform(-8, 25)), 3)
    return {"filmed_at": filmed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "filmed_local": filmed.strftime("%Y-%m-%dT%H:%M:%S%z"), "place": name, "lat": lat, "lon": lon, "alt": alt,
            "accuracy": round(rng.uniform(3, 15), 6), "location": f"{lat:+.4f}{lon:+09.4f}{alt:+08.3f}/",
            "make": identity.get("make", "Apple"), "model": identity["model"], "software": ios_at(identity, filmed),
            "kind": identity.get("kind", "iphone"), "android": identity.get("android")}


HOOK_FONT = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf") if Path(f).exists()), None)


def random_edit(rng: random.Random, hook: str | None = None, duration: float | None = None) -> dict:
    """The per-upload edit, strong enough that Instagram's picture and sound fingerprints see a different video
    (Luca, 2026-10-17: copies of one reel across many accounts were capped at a few hundred views). Every copy
    gets: mirror or not; the start untouched (Luca: the first frames are the hook) and a trimmed end; a speed of 97-103 %; a 5-10 % crop that drifts across the
    clip; a real colour grade with grain; the sound pitched 0.5-1.5 % up or down (Luca: 4 % made a voice squeaky) with an EQ tilt and faint room
    noise; and, when ``hook`` is given, a short text hook over the first seconds, placed differently each time.
    Different for every post."""
    speed = round(rng.uniform(0.97, 1.03), 4)
    trim_start = 0.0
    trim_end = round(rng.uniform(0.0, 0.8), 2)
    crop = round(rng.uniform(0.04, 0.08), 4)
    return {"mirror": rng.random() < 0.5, "trim_start": trim_start, "trim_end": trim_end, "speed": speed,
            "crop": crop, "x": round(rng.random(), 3), "y": round(rng.random(), 3), "drift": round(rng.uniform(-0.02, 0.02), 4),
            "temperature": round(rng.uniform(-0.08, 0.08), 3), "brightness": round(rng.uniform(-0.03, 0.03), 3),
            "contrast": round(rng.uniform(0.95, 1.08), 3), "saturation": round(rng.uniform(0.9, 1.12), 3),
            "gamma": round(rng.uniform(0.95, 1.05), 3), "grain": 0,   # no grain: Luca wants no quality drop (2026-10-17)
            "pitch": round(rng.choice((-1, 1)) * rng.uniform(0.005, 0.015), 4), "bass": round(rng.uniform(-2.5, 2.5), 2),
            "treble": round(rng.uniform(-2.5, 2.5), 2), "noise_db": 0, "db": round(rng.choice((-1, 1)) * rng.uniform(0.5, 1.5), 2),
            "hook": hook, "hook_pos": rng.choice(("top", "mid", "low")), "hook_seconds": round(rng.uniform(1.8, 3.2), 1),
            "hook_size": rng.choice((44, 50, 56)), "hook_box": rng.random() < 0.5}


def _audio_filters(edit: dict) -> str:
    """Pitch and tempo together (asetrate), speed to match the picture, an EQ tilt, faint noise, the volume nudge."""
    k = 1 + edit.get("pitch", 0.0)
    af = [f"asetrate=48000*{k:.4f}", "aresample=48000", f"atempo={edit.get('speed', 1.0) / k:.4f}"]
    if edit.get("bass"):
        af.append(f"bass=g={edit['bass']}")
    if edit.get("treble"):
        af.append(f"treble=g={edit['treble']}")
    af.append(f"volume={edit['db']}dB")
    return ",".join(af)


def _drawtext(edit: dict, height: int | None) -> str | None:
    hook = (edit.get("hook") or "").strip()
    if not hook or not HOOK_FONT:
        return None
    safe = hook.replace("\\", "").replace("'", "\\'").replace(":", "\\:").replace("%", "%%")
    y = {"top": "h*0.14", "mid": "(h-text_h)/2", "low": "h*0.72"}[edit.get("hook_pos", "top")]
    box = ":box=1:boxcolor=black@0.45:boxborderw=18" if edit.get("hook_box") else ":borderw=3:bordercolor=black@0.7"
    return (f"drawtext=fontfile='{HOOK_FONT}':text='{safe}':fontsize={edit.get('hook_size', 50)}:fontcolor=white{box}"
            f":x=(w-text_w)/2:y={y}:enable='lt(t,{edit.get('hook_seconds', 2.5)})'")


def _android_tags(meta: dict) -> list[tuple[str, str]]:
    """What Android's media muxer writes into a camera video: the creation time, the Android version and the
    location in ISO 6709 (the "@xyz" entry)."""
    loc = meta["location"]
    return [("creation_time", meta["filmed_at"]), ("com.android.version", str(meta.get("android") or "14")),
            ("location", loc), ("location-eng", loc)]


def _device_tags(meta: dict) -> list[tuple[str, str]]:
    return _android_tags(meta) if meta.get("kind") == "android" else _iphone_tags(meta)


def _iphone_tags(meta: dict) -> list[tuple[str, str]]:
    tags = [("creation_time", meta["filmed_at"])]
    if meta.get("accuracy"):
        tags.append(("com.apple.quicktime.location.accuracy.horizontal", f"{meta['accuracy']:.6f}"))
    return tags + [("com.apple.quicktime.location.ISO6709", meta["location"]), ("com.apple.quicktime.make", meta["make"]),
                   ("com.apple.quicktime.model", meta["model"]), ("com.apple.quicktime.software", meta.get("software", "")),
                   ("com.apple.quicktime.creationdate", meta.get("filmed_local") or meta["filmed_at"])]


def _video_filters(edit: dict, width: int | None, height: int | None) -> str:
    keep = 1 - edit["crop"]
    drift = edit.get("drift", 0.0)
    # the crop window drifts across the clip (a slow pan), never leaving the frame
    # commas inside a filter expression must be escaped, or ffmpeg reads them as the next filter
    x = f"clip(trunc((iw-ow)*{edit['x']}+iw*{drift}*t)\\,0\\,iw-ow)"
    y = f"clip(trunc((ih-oh)*{edit['y']}+ih*{drift}*0.5*t)\\,0\\,ih-oh)"
    vf = [f"crop=trunc(iw*{keep}/2)*2:trunc(ih*{keep}/2)*2:{x}:{y}"]
    if edit.get("mirror"):
        vf.append("hflip")
    if edit.get("speed") and edit["speed"] != 1:
        vf.append(f"setpts=PTS/{edit['speed']}")
    if width and height:
        vf.append(f"scale={width}:{height}:flags=lanczos")
    vf += ["setsar=1", f"eq=brightness={edit['brightness']}:contrast={edit['contrast']}:saturation={edit['saturation']}:gamma={edit.get('gamma', 1.0)}"]
    t = edit.get("temperature", 0.0)
    if t:
        vf.append(f"colorbalance=rs={t:.3f}:bs={-t:.3f}:rm={t / 2:.3f}:bm={-t / 2:.3f}")   # warm (+) or cool (-)
    if edit.get("hue"):
        vf.append(f"hue=h={edit['hue']}")
    if edit.get("grain"):
        vf.append(f"noise=alls={edit['grain']}:allf=t")
    dt = _drawtext(edit, height)
    if dt:
        vf.append(dt)
    vf += ["format=yuv420p", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"]
    return ",".join(vf)


async def _ffmpeg(args: list[str], timeout: int) -> str | None:
    """Run ffmpeg; None when it worked, else the error (missing, timed out or failed)."""
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return "timed out"
    except FileNotFoundError:
        return "ffmpeg is not installed"
    return None if proc.returncode == 0 else (err or b"").decode(errors="replace")[:200]


# ---------------------------------------------------------------------- iPhone-style header (moov atom)
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"dinf", b"stbl", b"edts"}


def _atoms(buf: bytes):
    i = 0
    while i + 8 <= len(buf):
        size, kind = int.from_bytes(buf[i:i + 4], "big"), buf[i + 4:i + 8]
        if size < 8 or i + size > len(buf):
            raise ValueError(f"bad atom {kind!r}")
        yield kind, buf[i + 8:i + size]
        i += size


def _iphone_atom(kind: bytes, body: bytes, parent: bytes) -> bytes:
    if kind in _CONTAINERS:
        body = b"".join(_iphone_atom(k, b, kind) for k, b in _atoms(body))
    elif kind == b"mdhd":
        at = 4 + (28 if body[0] == 1 else 16)
        if body[at:at + 2] == b"\x7f\xff":
            body = body[:at] + b"\x55\xc4" + body[at + 2:]
    elif kind == b"hdlr" and parent == b"minf" and body[8:12] in (b"url ", b"alis"):
        body = body[:8] + b"alis" + body[12:24] + bytes([23]) + b"Core Media Data Handler"
    elif kind == b"dref":
        body = body.replace(b"url \x00\x00\x00\x01", b"alis\x00\x00\x00\x01")
    elif kind == b"stsd" and body[4:8] == b"\x00\x00\x00\x01" and body[28:32] in (b"FFMP", b"\x00\x00\x00\x00"):
        body = body[:28] + b"appl" + body[32:]                # Apple as the vendor (bitexact leaves it blank)
    return (len(body) + 8).to_bytes(4, "big") + kind + body


def iphone_header(path: Path) -> bool:
    """Apple as the video vendor, "und" languages, Apple's data handler: only the moov atom (last in the file) is
    rewritten, the media data stays untouched. False if left as it was."""
    data = path.read_bytes()
    try:
        top, i = [], 0
        while i + 8 <= len(data):
            size, kind = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
            if size == 1:
                size = int.from_bytes(data[i + 8:i + 16], "big")
            elif size == 0:
                size = len(data) - i
            top.append((kind, i, size))
            i += size
        if not top or top[0][0] != b"ftyp" or top[-1][0] != b"moov" or i != len(data):
            return False
        _, at, size = top[-1]
        moov = _iphone_atom(b"moov", data[at + 8:at + size], b"")
    except (ValueError, IndexError):
        return False
    path.write_bytes(data[:at] + moov)
    return True


async def make_variant(src: Path, dest: Path, meta: dict) -> Path:
    """The .mp4 that goes up for one post: re-encoded (H.264 + 48 kHz stereo AAC, low priority, one thread) with
    ``meta["edit"]``, every original tag dropped, iPhone tags and handler names written in, no ffmpeg/x264 marks.
    If the re-encode fails the original picture and sound are kept with the new tags; without ffmpeg the file is
    copied. ``meta["edited"]`` records whether the edit made it in."""
    android = meta.get("kind") == "android"
    clean = ["-map_metadata", "-1", "-map_metadata:s", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    for k, v in _device_tags(meta):
        clean += ["-metadata", f"{k}={v}"]
    clean += ["-metadata:s:v", f"creation_time={meta['filmed_at']}", "-metadata:s:a", f"creation_time={meta['filmed_at']}"]
    if android:
        # an Android camera file: "mp42" brand, MediaMuxer's handler names, no encoder tag (Luca, 2026-10-17: the
        # metadata has to match the Samsung the post comes from)
        clean += ["-metadata:s:v", "handler_name=VideoHandle", "-metadata:s:a", "handler_name=SoundHandle",
                  "-movie_timescale", "1000", "-f", "mp4", "-brand", "mp42", "-movflags", "+use_metadata_tags", str(dest)]
    else:
        clean += ["-metadata:s:v", "handler_name=Core Media Video", "-metadata:s:a", "handler_name=Core Media Audio",
                  "-metadata:s:v", "encoder=H.264", "-movie_timescale", "600", "-f", "mov", "-movflags", "+use_metadata_tags", str(dest)]
    # "mov": a QuickTime file ("qt  " brand) like the iPhone camera writes; the name stays .mp4 because GeeLark takes
    # only mp4 uploads (Luca, 2026-10-16: close the gaps a file check could see)
    edit = meta.get("edit")
    done = False
    if edit:
        info = await probe(src)
        trim = ["-ss", f"{edit.get('trim_start', 0):.2f}"] if edit.get("trim_start") else []
        end = []
        if edit.get("trim_end") and info.get("duration"):
            end = ["-to", f"{max(1.0, float(info['duration']) - edit['trim_end']):.2f}"]
        args = ["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", *trim, *end, "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", _video_filters(edit, info.get("width"), info.get("height")), "-af", _audio_filters(edit),
                "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-maxrate", _maxrate(info), "-bufsize", _bufsize(info), "-profile:v", "high",
                "-video_track_timescale", "600", "-threads", "1", "-bsf:v", "filter_units=remove_types=6",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"] + clean
        err = await _ffmpeg(args, timeout=1200)
        done = err is None and dest.exists() and dest.stat().st_size > 0
        if not done:
            log.warning("ffmpeg edit failed for %s (%s); uploading it unedited with new tags", src.name, err)
    meta["edited"] = done
    if not done:
        err = await _ffmpeg(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0", "-c", "copy"] + clean, timeout=300)
        if err is not None or not dest.exists() or dest.stat().st_size == 0:
            log.warning("ffmpeg variant failed for %s (%s); uploading a plain copy", src.name, err)
            shutil.copyfile(src, dest)
            return dest
    if not android:
        await asyncio.to_thread(iphone_header, dest)
    return dest


# ---------------------------------------------------------------------- iPhone camera EXIF for pictures
# The cameras of the phones in IPHONES (main wide lens, front lens): focal length, aperture, 35 mm equivalent and the
# LensSpecification range Apple writes (shortest-longest focal length across the back lenses, f-numbers).
_BACK = {"iPhone 15 Pro": (6.765, 1.78, 24, (1.54, 9.0, 1.78, 2.8)), "iPhone 15 Pro Max": (6.765, 1.78, 24, (1.54, 15.66, 1.78, 2.8)),
         "iPhone 16 Pro": (6.765, 1.78, 24, (1.54, 15.66, 1.78, 2.8)), "iPhone 16 Pro Max": (6.765, 1.78, 24, (1.54, 15.66, 1.78, 2.8))}
_FRONT = (2.69, 1.9, 23, (2.69, 2.69, 1.9, 1.9))


def _rational(x: float, den: int = 1000):
    from PIL.TiffImagePlugin import IFDRational
    return IFDRational(int(round(x * den)), den)


def _dms(deg: float):
    deg = abs(deg)
    d = int(deg); m = int((deg - d) * 60); sec = (deg - d - m / 60) * 3600
    return (_rational(d, 1), _rational(m, 1), _rational(sec, 100))


def camera_exif(identity: dict, rng: random.Random, taken_utc: datetime, width: int, height: int, *, front: bool):
    """The tags an iPhone writes into a photo: camera and lens, exposure, local date and time with the UTC offset,
    and GPS from the account's home city (Luca, 2026-10-16: a real iPhone photo carries about forty tags, ours had six).
    Returns a PIL Exif ready for ``save(exif=...)``."""
    import math
    from PIL import Image
    from PIL.ExifTags import IFD
    model = identity.get("model", "iPhone 15 Pro")
    android = is_android(identity)
    make = identity.get("make", "Apple")
    name, lat, lon, tzname, elev = next((p for p in US_PLACES if p[0] == identity.get("home")), US_PLACES[0])
    local = taken_utc.astimezone(ZoneInfo(tzname))
    offset = local.strftime("%z"); offset = f"{offset[:3]}:{offset[3:]}"
    stamp = local.strftime("%Y:%m:%d %H:%M:%S")
    if android:
        _, _, back, fr = ANDROID_PHONES.get(identity.get("name", ""), (make, model, (5.5, 1.8, 26), (3.0, 2.2, 26)))
        focal, fnum, eq35 = fr if front else back
        spec, lens = None, None
    else:
        focal, fnum, eq35, spec = _FRONT if front else _BACK.get(model, _BACK["iPhone 15 Pro"])
        lens = f"{model} {'front camera' if front else 'back triple camera'} {focal:g}mm f/{fnum:g}"
    daylight = 8 <= local.hour < 18 and rng.random() < 0.75
    iso_ = rng.choice((32, 40, 50, 64, 80, 100) if daylight else (125, 160, 200, 250, 320, 400, 500, 640))
    exposure = rng.choice((1 / 2000, 1 / 1500, 1 / 1000, 1 / 750, 1 / 500, 1 / 350, 1 / 250) if daylight else (1 / 120, 1 / 100, 1 / 60, 1 / 50, 1 / 40, 1 / 30))
    tv, av = math.log2(1 / exposure), 2 * math.log2(fnum)
    bv = av + tv - math.log2(iso_ / 3.125)
    sub = f"{rng.randint(0, 999):03d}"
    exif = Image.Exif()
    exif[0x010F] = make; exif[0x0110] = model; exif[0x0112] = 1                          # Make, Model, Orientation
    exif[0x011A] = _rational(72, 1); exif[0x011B] = _rational(72, 1); exif[0x0128] = 2    # X/YResolution, ResolutionUnit
    exif[0x0131] = ios_at(identity, taken_utc); exif[0x0132] = stamp                      # Software, DateTime
    if android:
        exif[0x0213] = 1                                                                  # YCbCrPositioning (Samsung/Pixel: no HostComputer)
    else:
        exif[0x013C] = model; exif[0x0213] = 1                                            # HostComputer, YCbCrPositioning
    e = exif.get_ifd(IFD.Exif)
    e[0x829A] = _rational(exposure, 1_000_000); e[0x829D] = _rational(fnum, 100); e[0x8822] = 2       # ExposureTime, FNumber, Program
    e[0x8827] = iso_; e[0x9000] = b"0220" if android else b"0232"                                      # ISO, ExifVersion
    e[0x9003] = stamp; e[0x9004] = stamp; e[0x9010] = offset; e[0x9011] = offset; e[0x9012] = offset   # dates and offsets
    e[0x9201] = _rational(tv, 1000); e[0x9202] = _rational(av, 1000); e[0x9203] = _rational(bv, 1000)  # Shutter, Aperture, Brightness
    e[0x9204] = _rational(0, 1); e[0x9207] = 5; e[0x9209] = 16; e[0x920A] = _rational(focal, 1000)    # Bias, Metering, Flash off, FocalLength
    e[0x9214] = (width // 2, height // 2, max(1, width // 3), max(1, height // 3))                      # SubjectArea
    e[0x9291] = sub; e[0x9292] = sub; e[0xA000] = b"0100"; e[0xA001] = 1                               # SubSec, Flashpix, ColorSpace sRGB
    e[0xA002] = width; e[0xA003] = height; e[0xA217] = 2; e[0xA301] = b"\x01"                          # pixels, sensor, scene type
    e[0xA402] = 0; e[0xA403] = 0; e[0xA405] = eq35; e[0xA406] = 0                                      # auto exposure, auto WB, 35 mm, standard
    if android:
        e[0xA420] = "".join(rng.choice("0123456789ABCDEF") for _ in range(32))                        # ImageUniqueID (Samsung writes one)
        e[0xA401] = 0; e[0xA408] = 0; e[0xA409] = 0; e[0xA40A] = 0                                      # custom rendered, contrast, saturation, sharpness
    else:
        e[0xA432] = tuple(_rational(v, 1000) for v in spec); e[0xA433] = "Apple"; e[0xA434] = lens     # LensSpecification, LensMake, LensModel
    plat, plon = lat + rng.uniform(-0.012, 0.012), lon + rng.uniform(-0.012, 0.012)
    g = exif.get_ifd(IFD.GPSInfo)
    g[1] = "N" if plat >= 0 else "S"; g[2] = _dms(plat); g[3] = "E" if plon >= 0 else "W"; g[4] = _dms(plon)
    g[5] = 0; g[6] = _rational(max(1.0, elev + rng.uniform(-8, 25)), 1000)
    t = taken_utc.astimezone(timezone.utc)
    g[7] = (_rational(t.hour, 1), _rational(t.minute, 1), _rational(t.second, 1)); g[0x1D] = t.strftime("%Y:%m:%d")
    g[12] = "K"; g[13] = _rational(0, 1)                                                                # speed 0 km/h
    heading = rng.uniform(0, 360)
    g[16] = "T"; g[17] = _rational(heading, 1000); g[23] = "T"; g[24] = _rational(heading, 1000)       # direction, bearing
    g[31] = _rational(rng.uniform(3, 15), 1000)                                                         # HPositioningError
    return exif


def _strip_jfif(path: Path) -> None:
    """Pillow writes a JFIF header ahead of the EXIF; an iPhone JPEG starts with its EXIF block."""
    b = path.read_bytes()
    if b[:2] == b"\xff\xd8" and b[2:4] == b"\xff\xe0" and b[6:11] == b"JFIF\x00":
        n = int.from_bytes(b[4:6], "big")
        path.write_bytes(b[:2] + b[4 + n:])


# ---------------------------------------------------------------------- probing, checks, thumbnails
def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# The variant's bitrate ceiling follows the source clip (Luca, 2026-10-20: the proxy bills every megabyte, and an encode
# cannot hold more picture than the clip it came from): the source's own bitrate plus a 10 % margin for the edits,
# never below 3 Mbps, never above the old 16 Mbps ceiling. CRF 16 still decides the quality; the cap only stops
# the file growing past the original. IG_VARIANT_MAXRATE_MBPS pins a fixed ceiling instead.
def _maxrate(info: dict) -> str:
    fixed = os.environ.get("IG_VARIANT_MAXRATE_MBPS")
    if fixed:
        return f"{float(fixed):g}M"
    br = (info or {}).get("bit_rate")
    if not br:
        return "16M"
    mbps = min(16.0, max(3.0, br * 1.1 / 1_000_000))
    return f"{mbps:.1f}M"


def _bufsize(info: dict) -> str:
    return f"{float(_maxrate(info)[:-1]) * 2:.1f}M"


async def probe(path: Path) -> dict:
    """Duration and frame size via ffprobe. {} when ffprobe is not installed."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate:stream=codec_type,width,height", "-of", "json", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return {}
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        return {"unreadable": True}
    data = json.loads(out or b"{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    dur = (data.get("format") or {}).get("duration")
    br = (data.get("format") or {}).get("bit_rate")
    return {"duration": float(dur) if dur not in (None, "N/A") else None, "width": video.get("width"), "height": video.get("height"),
            "bit_rate": int(br) if br not in (None, "N/A") else None}


def check_reel(info: dict) -> list[str]:
    """Raise ValueError for files Instagram will refuse; return warnings for ones it may treat badly."""
    if info.get("unreadable"):
        raise ValueError("The file could not be read as a video")
    if info and not (info.get("width") and info.get("height")):
        raise ValueError("No video found in this file")
    warnings = []
    if info:
        d, w, h = info.get("duration"), info.get("width"), info.get("height")
        if d is not None and not 3 <= d <= 180:
            raise ValueError(f"Reels must be 3 seconds to 3 minutes; this one is {d:.0f} s")
        if w and h:
            if abs(w / h - 9 / 16) > 0.03:
                warnings.append(f"Not 9:16 ({w}x{h}); Instagram may crop it")
            if w < 540 or h < 960:
                warnings.append(f"Low resolution ({w}x{h}); 1080x1920 is recommended")
    return warnings


async def make_thumb(video: Path, out: Path) -> bool:
    """A small portrait JPG from the first second of the reel. Best effort."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(video), "-frames:v", "1", "-vf", "scale=270:-2",
            "-q:v", "4", str(out), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except (FileNotFoundError, asyncio.TimeoutError):
        return False
    return out.exists()


# ---------------------------------------------------------------------- profile pictures (2026-10-13)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def image_variant(src: Path, dst: Path, identity: dict, rng: random.Random, when: datetime | None = None, *,
                  size: int | None = 1080, max_side: int = 1440, mirror: float = 0.0, front: float = 0.3) -> dict:
    """One account's own copy of a picture: a small random crop shift, maybe a mirror, a tiny brightness/contrast
    nudge, a fresh JPEG, and iPhone EXIF from the account's own device identity. The person sees the same photo;
    the file, its hash and its metadata are new. ``size`` squares the output (profile pictures); None keeps the
    aspect, capped at ``max_side``. ``mirror`` is the chance of flipping left-right. Returns what was done."""
    from PIL import Image, ImageEnhance, ImageOps
    when = when or datetime.now(timezone.utc)
    taken = when - timedelta(minutes=rng.randint(40, 36 * 60))
    home = next((pl for pl in US_PLACES if pl[0] == identity.get("home")), US_PLACES[0])
    local = taken.astimezone(ZoneInfo(home[3]))
    if not 9 <= local.hour < 23:                          # taken during waking hours in her home city, never at 4 am
        day = local - timedelta(days=1) if local.hour < 9 else local
        local = day.replace(hour=rng.randint(10, 21), minute=rng.randint(0, 59), second=rng.randint(0, 59))
        taken = local.astimezone(timezone.utc)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        shift = rng.uniform(0.01, 0.03)                    # crop 1-3 % off, offset to a random side
        cw, ch = int(w * (1 - shift)), int(h * (1 - shift))
        x0, y0 = rng.randint(0, w - cw), rng.randint(0, h - ch)
        im = im.crop((x0, y0, x0 + cw, y0 + ch))
        if size:
            im = im.resize((size, size), Image.LANCZOS)
        elif max(im.size) > max_side:
            k = max_side / max(im.size)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        flipped = rng.random() < mirror
        if flipped:
            im = ImageOps.mirror(im)
        bright, contrast = rng.uniform(0.98, 1.02), rng.uniform(0.98, 1.02)
        im = ImageEnhance.Brightness(im).enhance(bright)
        im = ImageEnhance.Contrast(im).enhance(contrast)
        out_w, out_h = im.size
        exif = camera_exif(identity, rng, taken, out_w, out_h, front=rng.random() < front)
        quality = rng.randint(88, 94)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=quality, exif=exif.tobytes(), subsampling=0)
    _strip_jfif(dst)
    return {"shift": round(shift, 4), "offset": [x0, y0], "mirror": flipped, "brightness": round(bright, 3), "contrast": round(contrast, 3),
            "quality": quality, "taken": iso(taken), "model": identity.get("model"), "width": out_w, "height": out_h}


def story_image(src: Path, dst: Path, identity: dict, rng: random.Random, when: datetime | None = None) -> dict:
    """A 1080x1920 story made from one feed photo (Luca, 2026-10-18): the photo fitted in the middle over a blurred,
    darkened copy of itself, a hair of crop shift, a fresh JPEG with the phone's own EXIF."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    when = when or datetime.now(timezone.utc)
    taken = when - timedelta(minutes=rng.randint(20, 6 * 60))
    W, H = 1080, 1920
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        shift = rng.uniform(0.005, 0.02)
        cw, ch = int(w * (1 - shift)), int(h * (1 - shift))
        x0, y0 = rng.randint(0, w - cw), rng.randint(0, h - ch)
        im = im.crop((x0, y0, x0 + cw, y0 + ch))
        bg = ImageOps.fit(im, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(rng.randint(30, 50)))
        bg = ImageEnhance.Brightness(bg).enhance(rng.uniform(0.55, 0.7))
        k = min(W / im.width, (H * rng.uniform(0.72, 0.8)) / im.height)
        fg = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
        exif = camera_exif(identity, rng, taken, W, H, front=False)
        quality = rng.randint(88, 94)
        dst.parent.mkdir(parents=True, exist_ok=True)
        bg.save(dst, "JPEG", quality=quality, exif=exif.tobytes(), subsampling=0)
    _strip_jfif(dst)
    return {"shift": round(shift, 4), "quality": quality, "taken": iso(taken), "model": identity.get("model"), "width": W, "height": H}


def picture_variant(src: Path, dst: Path, identity: dict, rng: random.Random, when: datetime | None = None, size: int = 1080) -> dict:
    """A profile picture: square, never mirrored (a mirrored face next to the same face elsewhere looks odd)."""
    return image_variant(src, dst, identity, rng, when, size=size, mirror=0.0, front=0.7)       # mostly selfies


def photo_variant(src: Path, dst: Path, identity: dict, rng: random.Random, when: datetime | None = None) -> dict:
    """A feed photo: keeps its shape (capped at 1440 px), mirrored half the time, otherwise the same treatment."""
    return image_variant(src, dst, identity, rng, when, size=None, max_side=1440, mirror=0.5)
