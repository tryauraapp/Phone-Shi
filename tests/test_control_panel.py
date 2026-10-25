import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("control_panel", ROOT / "control-panel" / "server.py")
panel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(panel)


class ControlPanelTests(unittest.TestCase):
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
        self.assertTrue(identity["sw"])

    def test_reviewed_apps_expose_multiselect_and_randomizable_choices(self):
        self.assertEqual(set(panel.APP_SCHEMAS), {"bumble", "tinder", "pof"})
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


if __name__ == "__main__":
    unittest.main()
