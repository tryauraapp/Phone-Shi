import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nodemaven_proxy as nodemaven


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


class NodeMavenProxyTests(unittest.TestCase):
    def test_accepts_current_and_legacy_location_list_shapes(self):
        self.assertEqual(nodemaven.result_list({'results': [1]}, 'regions'), [1])
        self.assertEqual(nodemaven.result_list({'regions': [2]}, 'regions'), [2])

    def test_expired_key_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            path.write_text(jwt({"exp": 100}))
            path.chmod(0o600)
            with self.assertRaisesRegex(nodemaven.NodeMavenError, "expired"):
                nodemaven.read_api_key(path)

    def test_key_file_must_be_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            path.write_text("not-a-secret-example")
            path.chmod(0o644)
            with self.assertRaisesRegex(nodemaven.NodeMavenError, "permissions 600"):
                nodemaven.read_api_key(path)

    def test_prefers_high_availability_tmobile_inventory(self):
        selected = nodemaven.choose_tmobile([
            {"name": "T-Mobile", "code": "tmobile_slow", "effective_availability": "medium"},
            {"name": "T-Mobile", "code": "tmobile_fast", "effective_availability": "high"},
            {"name": "AT&T", "code": "att", "effective_availability": "high"},
        ])
        self.assertEqual(selected["code"], "tmobile_fast")

    def test_provisions_mobile_us_tmobile_with_nodemaven_quality_spelling(self):
        calls = []

        def request(key, method, endpoint, **kwargs):
            calls.append((method, endpoint, kwargs))
            if endpoint == "/users/me":
                return {"proxy_username": "account_user", "proxy_password": "private_password"}
            if endpoint == "/locations/isps/":
                return {"isps": [{"name": "T-Mobile", "code": "t_mobile",
                                   "effective_availability": "high"}]}
            if endpoint == "/proxy-checks/location":
                return {"status": "failed", "location_match": False, "exit_ip": "192.0.2.4",
                        "isp": "T-Mobile USA, Inc.", "proxy_type": "mobile",
                        "mismatched": [{"level": "isp", "expected": "t_mobile",
                                        "observed": "T-Mobile USA, Inc."}],
                        "observed": {"country": "US", "isp": "T-Mobile USA, Inc."},
                        "checked_at": "2026-10-25T04:00:00Z"}
            raise AssertionError(endpoint)

        with patch.object(nodemaven.secrets, "token_hex", return_value="abcdef0123456789"):
            proxy, metadata = nodemaven.provision("api-key", request)
        self.assertIn("-country-us-isp-t_mobile-type-mobile-sid-abcdef0123456789-norotate-true-filter-medium", proxy)
        self.assertNotIn("filter-high", proxy)
        self.assertEqual(metadata["connection_type"], "mobile")
        self.assertEqual(metadata["availability"], "high")
        location_query = calls[1][2]["query"]
        self.assertEqual(location_query["country__code"], "us")
        self.assertEqual(location_query["connection_type"], "mobile")
        check = calls[2][2]["body"]
        self.assertEqual(check["config"]["targeting"], {"country": "us", "isp": "t_mobile"})
        self.assertEqual(check["config"]["session_mode"], "no_rotation")
        self.assertNotIn("ttl_seconds", check["config"])
        self.assertEqual(check["timeout_seconds"], 20)
        self.assertNotIn("private_password", json.dumps(metadata))

    def test_failed_location_check_writes_nothing(self):
        def request(key, method, endpoint, **kwargs):
            if endpoint == "/users/me":
                return {"proxy_username": "account_user", "proxy_password": "password_1"}
            if endpoint == "/locations/isps/":
                return {"isps": [{"name": "T-Mobile", "code": "t_mobile"}]}
            return {"status": "failed", "location_match": False, "proxy_type": "mobile",
                    "isp": "AT&T", "observed": {"country": "us", "isp": "AT&T"}}

        with self.assertRaisesRegex(nodemaven.NodeMavenError, "could not verify"):
            nodemaven.provision("api-key", request)

    def test_city_targeting_is_verified_and_persisted(self):
        def request(key, method, endpoint, **kwargs):
            if endpoint == "/users/me":
                return {"proxy_username": "account_user", "proxy_password": "private_password"}
            if endpoint == "/locations/regions/":
                return {"regions": [{"name": "Texas", "code": "texas"}]}
            if endpoint == "/locations/cities/":
                return {"cities": [{"name": "Houston", "code": "houston",
                                      "region": {"name": "Texas", "code": "texas"}}]}
            if endpoint == "/locations/isps/":
                return {"isps": [{"name": "T-Mobile USA", "code": "t_mobile_usa",
                                    "effective_availability": "high"}]}
            if endpoint == "/proxy-checks/location":
                return {"exit_ip": "192.0.2.4", "isp": "T-Mobile USA, Inc.",
                        "proxy_type": "mobile", "observed": {
                            "country": "US", "region": "Texas", "city": "Houston",
                            "isp": "T-Mobile USA, Inc."}}
            raise AssertionError(endpoint)

        with patch.object(nodemaven.secrets, "token_hex", return_value="abcdef0123456789"):
            proxy, metadata = nodemaven.provision(
                "api-key", request, region="Texas", city="Houston")
        self.assertIn("-region-texas-city-houston-isp-t_mobile_usa-", proxy)
        self.assertEqual(metadata["targeting"]["city"]["code"], "houston")
        self.assertEqual(metadata["targeting"]["region"]["code"], "texas")

    def test_private_write_is_atomic_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy"
            nodemaven.private_write(path, "secret\n")
            self.assertEqual(path.read_text(), "secret\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
