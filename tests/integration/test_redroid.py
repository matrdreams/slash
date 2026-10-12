"""Live Redroid checks. Skipped unless SLASH_ADB_SERIAL is set.

The serial is an adb address such as 127.0.0.1:5601. These tests connect,
read boot_completed, take a screenshot, parse a uiautomator dump, tap and
press HOME, and send ADBKeyBoard text when that IME is installed.
"""

import asyncio
import os

import pytest

from slash.agent.actuator import input_broadcast
from slash.agent.tree import parse_hierarchy
from slash.devices.adb import AdbClient

SERIAL = os.environ.get("SLASH_ADB_SERIAL", "").strip()
pytestmark = pytest.mark.skipif(
    not SERIAL,
    reason="set SLASH_ADB_SERIAL to a booted redroid adb serial",
)


def _adb() -> AdbClient:
    return AdbClient()


def test_boot_completed():
    adb = _adb()

    async def scenario():
        await adb.connect(SERIAL)
        return (await adb.getprop(SERIAL, "sys.boot_completed")).strip()

    assert asyncio.run(scenario()) == "1"


def test_screenshot_is_png():
    adb = _adb()

    async def scenario():
        await adb.connect(SERIAL)
        return await adb.exec_out(SERIAL, "screencap -p")

    png = asyncio.run(scenario())
    assert png.startswith(b"\x89PNG")


def test_uiautomator_dump_parses():
    adb = _adb()

    async def scenario():
        await adb.connect(SERIAL)
        xml_text = ""
        for _ in range(3):
            await adb.shell(SERIAL, "uiautomator dump /sdcard/slash_uidump.xml")
            xml_text = await adb.shell(SERIAL, "cat /sdcard/slash_uidump.xml")
            if "<hierarchy" in xml_text:
                return xml_text
            await asyncio.sleep(1)
        return xml_text

    xml_text = asyncio.run(scenario())
    assert "<hierarchy" in xml_text
    nodes = parse_hierarchy(xml_text)
    assert isinstance(nodes, list)


def test_tap_and_home_key():
    adb = _adb()

    async def scenario():
        await adb.connect(SERIAL)
        await adb.shell(SERIAL, "input tap 360 640")
        await adb.shell(SERIAL, "input keyevent 3")

    asyncio.run(scenario())


def test_adbkeyboard_text_when_installed():
    adb = _adb()

    async def scenario():
        await adb.connect(SERIAL)
        listed = await adb.shell(SERIAL, "pm path com.android.adbkeyboard")
        if "package:" not in listed:
            pytest.skip("ADBKeyBoard is not installed on this device")
        await adb.shell(SERIAL, "ime set com.android.adbkeyboard/.AdbIME")
        return await adb.shell(SERIAL, input_broadcast("测试"))

    result = asyncio.run(scenario())
    assert "Broadcast completed" in result or "result=" in result
