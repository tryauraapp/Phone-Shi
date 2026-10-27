import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("control_panel", ROOT / "control-panel" / "server.py")
panel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(panel)


class ControlPanelTests(unittest.TestCase):
    def test_phone_share_token_is_scoped_signed_and_expires(self):
        secret = b"test-secret"
        token = panel.encode_phone_share("Galaxy_S25_Test", secret, expires=200)
        self.assertEqual(
            panel.decode_phone_share(token, secret, timestamp=199),
            {"avd": "Galaxy_S25_Test", "expires": 200})
        self.assertIsNone(panel.decode_phone_share(token + "x", secret, timestamp=199))
        self.assertIsNone(panel.decode_phone_share(token, secret, timestamp=201))

    def test_share_base_accepts_only_bare_http_origins(self):
        self.assertEqual(panel.safe_share_base("https://phones.example.com/"),
                         "https://phones.example.com")
        self.assertEqual(panel.safe_share_base("http://100.64.0.10:8790"),
                         "http://100.64.0.10:8790")
        self.assertEqual(panel.safe_share_base("https://user:pass@example.com"), "")
        self.assertEqual(panel.safe_share_base("javascript:alert(1)"), "")
        self.assertEqual(panel.safe_share_base("https://example.com/path"), "")

    def test_provisioning_phone_appears_before_avd_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "data/provisioning/VPS_Phone_Test"
            job.mkdir(parents=True)
            (job / "status.json").write_text(json.dumps({
                "phase": "manual-required", "stage": "google-play",
                "progress": 82, "message": "Install Tinder"}))
            (job / "request.json").write_text(json.dumps({
                "app": "tinder", "city": "Houston", "region": "Texas"}))
            old = (panel.DATA, panel.DB, panel.PHONE_BACKUPS)
            panel.DATA, panel.DB = root / "data", root / "data/panel.sqlite3"
            panel.PHONE_BACKUPS = root / "backups"
            try:
                with patch.object(panel, "inventory", return_value=([], [], {})):
                    phone = panel.fleet_inventory()[0]
            finally:
                panel.DATA, panel.DB, panel.PHONE_BACKUPS = old
            self.assertEqual(phone["avd"], "VPS_Phone_Test")
            self.assertEqual(phone["phase"], "manual-required")
            self.assertEqual(phone["apps"], ["Tinder"])
            self.assertEqual(phone["provisioning"]["progress"], 82)

    def test_creator_schema_migrates_and_decodes_saved_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "panel.sqlite3"
            with sqlite3.connect(database) as legacy:
                legacy.execute(
                    "CREATE TABLE creators(id TEXT PRIMARY KEY,name TEXT NOT NULL,"
                    "notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)")
                legacy.execute(
                    "INSERT INTO creators VALUES(?,?,?,?)",
                    ("creator_test", "Bella", "note", panel.now()))
            old_data, old_db = panel.DATA, panel.DB
            panel.DATA, panel.DB = Path(directory), database
            try:
                with panel.connect() as db:
                    columns = {row["name"] for row in db.execute("PRAGMA table_info(creators)")}
                    creator = panel.row_json(
                        db.execute("SELECT * FROM creators WHERE id='creator_test'").fetchone())
            finally:
                panel.DATA, panel.DB = old_data, old_db
            self.assertIn("profiles_json", columns)
            self.assertEqual(creator["profiles"], {})

    def test_creator_row_decodes_profiles_by_app(self):
        row = {"id": "creator_test", "profiles_json": json.dumps({
            "tinder": {"relationship_goal": "Long-term partner"}})}
        self.assertEqual(
            panel.row_json(row)["profiles"]["tinder"]["relationship_goal"],
            "Long-term partner")

    def test_saved_screen_fixture_redacts_text_entry_values(self):
        xml = (b'<hierarchy><node class="android.widget.TextView" text="Birthday"/>'
               b'<node class="android.widget.EditText" text="private value" '
               b'content-desc="typed value"/><node class="android.widget.EditText" '
               b'password="true" text="secret"/></hierarchy>')
        cleaned = panel.sanitize_ui_xml(xml).decode()
        self.assertIn('text="Birthday"', cleaned)
        self.assertNotIn("private value", cleaned)
        self.assertNotIn("typed value", cleaned)
        self.assertNotIn("secret", cleaned)
        self.assertEqual(cleaned.count("[redacted]"), 3)

    def test_s25_identity_matches_phone_and_keeps_home_city(self):
        location = {"label": "Miami, Florida, United States", "latitude": 25.77,
                    "longitude": -80.21, "timezone": "America/New_York"}
        identity = panel.identity_for("account-test", {"brand": "samsung", "name": "Galaxy S25"}, location)
        self.assertEqual(identity["kind"], "android")
        self.assertEqual(identity["make"], "samsung")
        self.assertEqual(identity["model"], "SM-S931B")
        self.assertEqual(identity["android"], "15")
        self.assertEqual(identity["home"], location["label"])
        self.assertEqual(identity["proxy_location"], location)
        self.assertEqual(identity["sw"], [["2000-01-01T00:00:00+00:00", "S931BXXS4AYF1"]])

    def test_reviewed_apps_expose_multiselect_and_randomizable_choices(self):
        self.assertTrue({"bumble", "tinder", "pof"}.issubset(panel.APP_SCHEMAS))
        self.assertTrue({
            "hinge", "okcupid", "match", "eharmony", "coffee-meets-bagel",
            "facebook-dating", "feeld", "zoosk", "badoo", "elitesingles",
            "hily", "happn",
        }.issubset(panel.APP_SCHEMAS))
        bumble = {q["key"]: q for q in panel.APP_SCHEMAS["bumble"]["questions"]}
        tinder = {q["key"]: q for q in panel.APP_SCHEMAS["tinder"]["questions"]}
        self.assertTrue(bumble["interests"]["multiple"])
        self.assertEqual(bumble["interests"]["count"], 5)
        self.assertTrue(tinder["interests"]["multiple"])
        self.assertEqual(tinder["interests"]["count"], [2, 3])
        self.assertIn("Still figuring it out", tinder["relationship_goal"]["options"])

    def test_inventory_accepts_space_padded_adb_device_rows(self):
        def run(command, **kwargs):
            if command == ["adb", "devices", "-l"]:
                output = ("List of devices attached\n"
                          "emulator-5554          device product:pa1qxxx model:SM_S931B\n")
            elif command[:4] == ["adb", "-s", "emulator-5554", "shell"]:
                output = "Galaxy_S25_Test\n"
            elif command == ["emulator", "-list-avds"]:
                output = "Galaxy_S25_Test\n"
            else:
                raise AssertionError(command)
            return subprocess.CompletedProcess(command, 0, output, "")

        with patch.object(panel.subprocess, "run", side_effect=run), \
                patch.object(panel, "saved_phone_profiles", return_value={}):
            devices, avds, _ = panel.inventory()
        self.assertEqual(devices, [{"serial": "emulator-5554", "avd": "Galaxy_S25_Test"}])
        self.assertIn("Galaxy_S25_Test", avds)

    def test_fleet_inventory_reports_city_bound_phone_without_pinning_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backups = root / "backups"
            setup = backups / "Galaxy_S25_Test/setup"
            setup.mkdir(parents=True)
            (setup / "setup-complete.json").write_text(json.dumps({"avd": "Galaxy_S25_Test"}))
            (setup / "proxy-location.json").write_text(json.dumps({
                "label": "Houston, Texas, United States", "latitude": 29.76,
                "longitude": -95.37, "timezone": "America/Chicago"}))
            (setup / "nodemaven-proxy").write_text("private")
            (setup / "nodemaven-proxy.json").write_text(json.dumps({"targeting": {
                "city": {"name": "Houston"}, "region": {"name": "Texas"},
                "isp": {"name": "T-Mobile USA"}}}))
            for relative in ("profile/device-profile.json", "profile/battery.conf",
                             "profile/radio-state.json", "location/location-state.json"):
                path = setup / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
            avd_home = root / "avds"
            camera = avd_home / "Galaxy_S25_Test.avd/camera/native-camera.json"
            camera.parent.mkdir(parents=True)
            camera.write_text(json.dumps({"prepared_video": "/private/front.webm", "fps": 30,
                                          "preview_size": [1080, 1440],
                                          "status": "verified_camera2_pixels"}))
            old_backups, old_data = panel.PHONE_BACKUPS, panel.DATA
            panel.PHONE_BACKUPS, panel.DATA = backups, root / "data"
            panel.FLEET_JOBS.clear()
            try:
                with patch.dict(os.environ, {"ANDROID_AVD_HOME": str(avd_home)}), \
                        patch.object(panel, "inventory", return_value=(
                            [], ["Galaxy_S25_Test"], {})):
                    phone = panel.fleet_inventory()[0]
            finally:
                panel.PHONE_BACKUPS, panel.DATA = old_backups, old_data
            self.assertTrue(phone["certified"])
            self.assertEqual(phone["phase"], "stopped")
            self.assertEqual(phone["proxy"]["policy"], "city-bound")
            self.assertTrue(phone["proxy"]["rotationAllowed"])
            self.assertEqual(phone["proxy"]["radiusMiles"], 100)
            self.assertTrue(all(check["ok"] for check in phone["checks"]))

    def test_launch_phone_uses_guarded_launcher(self):
        process = MagicMock(pid=4123)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(panel, "DATA", Path(directory)), \
                patch.object(panel, "require_phone", return_value={
                    "certified": True, "phase": "stopped"}), \
                patch.object(panel.subprocess, "Popen", return_value=process) as popen:
            panel.FLEET_JOBS.clear()
            result = panel.launch_phone("Galaxy_S25_Test")
        command = popen.call_args.args[0]
        self.assertIn(str(ROOT / "emulator_proxy.py"), command)
        self.assertEqual(command[-2:], ["--avd", "Galaxy_S25_Test"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(result["phase"], "starting")

    def test_camera_upload_uses_complete_swap_helper_and_restarts_running_phone(self):
        class VideoPart:
            def get_filename(self): return "new-camera.mp4"
            def get_content_type(self): return "video/mp4"
            def get_payload(self, decode=False): return b"video-bytes"

        process = MagicMock(pid=5511)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(panel, "DATA", Path(directory)), \
                patch.object(panel, "require_phone", return_value={
                    "certified": True, "phase": "ready"}), \
                patch.object(panel, "verify_uploaded_video", return_value={
                    "width": 1080, "height": 1440, "duration": 8.0,
                    "frameRate": "30/1"}), \
                patch.object(panel.subprocess, "Popen", return_value=process) as popen:
            panel.FLEET_JOBS.clear()
            result = panel.replace_camera_video("Galaxy_S25_Test", VideoPart())
        command = popen.call_args.args[0]
        self.assertIn(str(ROOT / "swap_camera_video.py"), command)
        self.assertIn("--restart", command)
        self.assertEqual(result["media"]["width"], 1080)
        self.assertEqual(result["filename"], "new-camera.mp4")


if __name__ == "__main__":
    unittest.main()
