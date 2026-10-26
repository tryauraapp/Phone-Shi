#!/usr/bin/env python3
"""Provision one verified NodeMaven Mobile/US/T-Mobile proxy per AVD."""

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.nodemaven.com/api/v2/base"
ROOT = Path(__file__).resolve().parent
DEFAULT_KEY_FILE = ROOT / ".local" / "nodemaven-api-key"
DEFAULT_PROXY_ROOT = Path.home() / "galaxy_s25_avd_backups"


class NodeMavenError(RuntimeError):
    pass


def read_api_key(path):
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise NodeMavenError("NodeMaven API key file must have permissions 600.")
    key = path.read_text().strip()
    if not key or any(character.isspace() for character in key):
        raise NodeMavenError("NodeMaven API key must be one nonempty line.")
    # NodeMaven currently issues JWT-shaped API keys. Reject an expired one
    # locally so it is never copied into another file or sent needlessly.
    parts = key.split(".")
    if len(parts) == 3:
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            expires = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
        else:
            if int(expires) <= int(datetime.now(timezone.utc).timestamp()):
                when = datetime.fromtimestamp(int(expires), timezone.utc).isoformat()
                raise NodeMavenError(f"NodeMaven API key expired at {when}.")
    return key


def api_request(key, method, endpoint, *, query=None, body=None, opener=urlopen):
    url = API_ROOT + endpoint
    if query:
        url += "?" + urlencode(query)
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, method=method, headers={
        "Authorization": "x-api-key " + key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Phone-Shi-NodeMaven/1",
    })
    try:
        with opener(request, timeout=45) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise NodeMavenError("NodeMaven rejected the API key or the account has no active proxy access.") from exc
        detail = ""
        try:
            error = json.loads(exc.read(65536))

            def redact(value):
                if isinstance(value, dict):
                    return {name: ("[redacted]" if any(part in name.lower()
                                                       for part in ("password", "username", "token", "key"))
                                   else redact(item)) for name, item in value.items()}
                if isinstance(value, list):
                    return [redact(item) for item in value]
                return value

            detail = " " + json.dumps(redact(error), separators=(",", ":"))[:1000]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        raise NodeMavenError(f"NodeMaven API returned HTTP {exc.code}.{detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise NodeMavenError("Could not reach the NodeMaven API.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise NodeMavenError("NodeMaven returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise NodeMavenError("NodeMaven returned an unexpected response.")
    return result


def choose_tmobile(isps):
    def canonical(value):
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    choices = [item for item in isps if isinstance(item, dict)
               and "tmobile" in canonical(item.get("name", ""))]
    exact = [item for item in choices if canonical(item.get("name")) == "tmobile"]
    selected = (exact or choices)
    if not selected:
        raise NodeMavenError("NodeMaven reports no US Mobile T-Mobile inventory.")
    selected.sort(key=lambda item: (item.get("effective_availability") != "high",
                                    str(item.get("name", ""))))
    code = str(selected[0].get("code", "")).strip()
    if not code or not re.fullmatch(r"[a-zA-Z0-9_]+", code):
        raise NodeMavenError("NodeMaven returned an invalid T-Mobile ISP code.")
    return selected[0]


def canonical(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def result_list(response, legacy_key):
    """Accept both the current paginated API and its former named-list shape."""
    items = response.get("results")
    if items is None:
        items = response.get(legacy_key, [])
    return items if isinstance(items, list) else []


def choose_named(items, name, kind, parent=None):
    """Select one exact API location without silently broadening its scope."""
    wanted = canonical(name)
    matches = []
    for item in items:
        if not isinstance(item, dict) or canonical(item.get("name")) != wanted:
            continue
        if parent:
            observed = item.get("region") or {}
            if canonical(observed.get("code")) != canonical(parent.get("code")):
                continue
        matches.append(item)
    if len(matches) != 1:
        raise NodeMavenError(f"NodeMaven did not return one exact {kind} match for {name}.")
    code = str(matches[0].get("code", "")).strip()
    if not code or not re.fullmatch(r"[a-zA-Z0-9_]+", code):
        raise NodeMavenError(f"NodeMaven returned an invalid {kind} code.")
    return matches[0]


def base_credentials(key, request=api_request):
    account = request(key, "GET", "/users/me")
    username = str(account.get("proxy_username", "")).strip()
    password = str(account.get("proxy_password", "")).strip()
    if not username or not password:
        raise NodeMavenError("NodeMaven did not return proxy credentials for this account.")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", username):
        raise NodeMavenError("NodeMaven returned an unsafe base proxy username.")
    return username, password


def provision(key, request=api_request, *, region=None, city=None):
    if city and not region:
        raise NodeMavenError("City targeting requires a region.")
    username, password = base_credentials(key, request)
    selected_region = selected_city = None
    if region:
        regions = request(key, "GET", "/locations/regions/", query={
            "limit": 1000,
            "offset": 0,
            "country__code": "us",
            "name": region,
        })
        selected_region = choose_named(result_list(regions, "regions"), region, "region")
    if city:
        cities = request(key, "GET", "/locations/cities/", query={
            "limit": 1000,
            "offset": 0,
            "country__code": "us",
            "name": city,
        })
        selected_city = choose_named(result_list(cities, "cities"), city, "city", selected_region)
    locations = request(key, "GET", "/locations/isps/", query={
        "limit": 1000,
        "offset": 0,
        "country__code": "us",
        "connection_type": "mobile",
        "ipv4_only": "true",
        "name": "T-Mobile",
    })
    isp = choose_tmobile(result_list(locations, "isps"))
    targeting = {"country": "us", "isp": isp["code"]}
    if selected_region:
        targeting["region"] = selected_region["code"]
    if selected_city:
        targeting["city"] = selected_city["code"]
    config = {
        "proxy_type": "mobile",
        "protocol": "http",
        "session_mode": "no_rotation",
        "targeting": targeting,
    }
    checked = request(key, "POST", "/proxy-checks/location", body={
        "credentials": {"username": username, "password": password},
        "config": config,
        "timeout_seconds": 20,
    })
    observed = checked.get("observed") or {}
    observed_country = str(observed.get("country", "")).lower()
    observed_isp = re.sub(r"[^a-z0-9]", "", str(checked.get("isp") or observed.get("isp") or "").lower())
    # NodeMaven currently reports an ISP mismatch when it compares the target
    # code (t_mobile_usa) with the observed display name (T-Mobile USA, Inc.).
    # Verify the material exit properties instead of requiring those two label
    # formats to be textually identical.
    if (observed_country not in ("us", "usa", "unitedstates")
            or "tmobile" not in observed_isp
            or checked.get("proxy_type") != "mobile"
            or not checked.get("exit_ip")):
        raise NodeMavenError("NodeMaven could not verify a US T-Mobile mobile exit; no proxy was saved.")
    if selected_region and canonical(observed.get("region")) != canonical(selected_region["name"]):
        raise NodeMavenError("NodeMaven could not verify the requested region; no proxy was saved.")
    if selected_city and canonical(observed.get("city")) != canonical(selected_city["name"]):
        raise NodeMavenError("NodeMaven could not verify the requested city; no proxy was saved.")

    session = secrets.token_hex(8)
    # NodeMaven calls its highest-quality mode “Quality” in the dashboard but
    # requires the internal username spelling filter-medium. filter-high is not
    # a documented parameter.
    location_parts = "-country-us"
    if selected_region:
        location_parts += f"-region-{selected_region['code']}"
    if selected_city:
        location_parts += f"-city-{selected_city['code']}"
    full_username = (f"{username}{location_parts}-isp-{isp['code']}-type-mobile-"
                     f"sid-{session}-norotate-true-filter-medium")
    proxy = (f"http://{quote(full_username, safe='')}:{quote(password, safe='')}"
             "@gate.nodemaven.com:8080")
    metadata = {
        "provider": "NodeMaven",
        "country": "us",
        "connection_type": "mobile",
        "isp": isp["name"],
        "isp_code": isp["code"],
        "availability": isp.get("effective_availability"),
        "session": session,
        "session_mode": "no_rotation",
        "quality_mode": "Quality",
        "username_filter_parameter": "filter-medium",
        "targeting": {
            "country": {"code": "us", "name": "United States"},
            "region": ({"code": selected_region["code"], "name": selected_region["name"]}
                       if selected_region else None),
            "city": ({"code": selected_city["code"], "name": selected_city["name"]}
                     if selected_city else None),
            "isp": {"code": isp["code"], "name": isp["name"]},
        },
        "verified_exit_ip": checked.get("exit_ip"),
        "verified_observed": observed,
        "verified_at": checked.get("checked_at"),
        "nodemaven_location_match": checked.get("location_match"),
        "nodemaven_mismatched": checked.get("mismatched", []),
    }
    return proxy, metadata


def private_write(path, contents):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            descriptor = -1
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def phone_proxy_path(avd, home=None):
    root = Path(home) if home else DEFAULT_PROXY_ROOT
    return root / avd / "setup" / "nodemaven-proxy"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avd", required=True)
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
    parser.add_argument("--output")
    parser.add_argument("--region", help="Exact NodeMaven US region name, for example Texas")
    parser.add_argument("--city", help="Exact city within --region, for example Houston")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.avd):
        parser.error("Invalid AVD name.")
    output = Path(args.output) if args.output else phone_proxy_path(args.avd)
    try:
        proxy, metadata = provision(read_api_key(args.key_file), region=args.region, city=args.city)
        private_write(output, proxy + "\n")
        private_write(output.with_suffix(".json"), json.dumps(metadata, indent=2) + "\n")
    except (OSError, NodeMavenError) as exc:
        parser.exit(2, f"NodeMaven provisioning failed: {exc}\n")
    print(f"Verified private NodeMaven proxy saved for {args.avd}.")


if __name__ == "__main__":
    main()
