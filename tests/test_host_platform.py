import os
from pathlib import Path
from unittest import mock

import host_platform


def test_linux_defaults_to_standard_user_sdk():
    with mock.patch("platform.system", return_value="Linux"), \
         mock.patch("platform.machine", return_value="x86_64"):
        assert host_platform.host_tag() == "linux-x86_64"
        assert host_platform.android_abi() == "x86_64"
        assert host_platform.android_sdk_root({}) == Path.home() / "Android/Sdk"


def test_configured_sdk_wins():
    assert host_platform.android_sdk_root({"ANDROID_SDK_ROOT": "/opt/android-sdk"}) == \
        Path("/opt/android-sdk")


def test_mac_arm_mapping():
    with mock.patch("platform.system", return_value="Darwin"), \
         mock.patch("platform.machine", return_value="arm64"):
        assert host_platform.host_tag() == "darwin-aarch64"
        assert host_platform.android_abi() == "arm64-v8a"
