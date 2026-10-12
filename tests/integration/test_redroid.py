"""Live Redroid checks via uiautomator2. Skipped unless SLASH_ADB_SERIAL is set."""

import os

import pytest

from slash.devices.u2 import U2Device, find_in_hierarchy

SERIAL = os.environ.get("SLASH_ADB_SERIAL", "").strip()
pytestmark = pytest.mark.skipif(not SERIAL, reason="set SLASH_ADB_SERIAL to a booted redroid adb serial")


def test_u2_dump_screenshot_and_settings():
    dev = U2Device.connect(SERIAL)
    xml = dev.dump_hierarchy()
    assert "<hierarchy" in xml
    assert isinstance(find_in_hierarchy(xml), list)
    assert dev.screenshot_png().startswith(b"\x89PNG")
    assert dev.get_setting("global", "airplane_mode_on") in {"0", "1"}
