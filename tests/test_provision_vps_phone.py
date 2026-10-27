import json
from pathlib import Path
import tempfile
import unittest

import provision_vps_phone as worker


class VpsPhoneProvisioningTests(unittest.TestCase):
    def test_phone_name_validation_is_bounded(self):
        self.assertEqual(worker.valid_name("VPS_Phone_01"), "VPS_Phone_01")
        for value in ("x", "../phone", "phone name", "a" * 65):
            with self.assertRaises(ValueError):
                worker.valid_name(value)

    def test_status_updates_are_private_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            job = worker.Job(directory, "VPS_Phone_01")
            job.update("provisioning", "proxy", 28, "Provisioning proxy")
            saved = json.loads(job.status_path.read_text())
            self.assertEqual(saved["phase"], "provisioning")
            self.assertEqual(saved["progress"], 28)
            self.assertEqual(job.status_path.stat().st_mode & 0o777, 0o600)

    def test_config_update_preserves_unrelated_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("hw.audioInput=yes\nhw.ramSize=1024\n")
            worker.set_config(path, {"hw.ramSize": 2048, "hw.cpu.ncore": 4})
            values = dict(line.split("=", 1) for line in path.read_text().splitlines())
            self.assertEqual(values["hw.audioInput"], "yes")
            self.assertEqual(values["hw.ramSize"], "2048")
            self.assertEqual(values["hw.cpu.ncore"], "4")


if __name__ == "__main__":
    unittest.main()
