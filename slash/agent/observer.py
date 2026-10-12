"""Observation: uiautomator dump plus screencap. uiautomator2 is optional and not required."""

import asyncio
from dataclasses import dataclass, field

from slash.agent.imageutil import redact_png, scale_long_edge
from slash.agent.tree import UINode, compress, parse_hierarchy
from slash.devices.adb import SupportsAdb

DUMP_REMOTE = "/sdcard/slash_uidump.xml"


@dataclass
class Observation:
    tree_text: str
    nodes: list[UINode]
    screenshot: bytes
    screenshot_for_llm: bytes
    redacted: bool = False
    package: str = ""
    raw_xml: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)


class Observer:
    def __init__(self, adb: SupportsAdb, *, long_edge: int = 1024, tree_limit: int = 80) -> None:
        self.adb = adb
        self.long_edge = long_edge
        self.tree_limit = tree_limit

    async def observe(self, serial: str, *, mode: str = "tree+vision") -> Observation:
        if mode == "vision-only":
            return await self._vision_only(serial)
        xml_text = ""
        error = ""
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt:
                # uiautomator prints "could not get idle state" and writes nothing while
                # an activity is still animating (seen on Redroid right after launch).
                await asyncio.sleep(1.0)
            try:
                await self.adb.shell(serial, f"uiautomator dump {DUMP_REMOTE}")
                xml_text = await self.adb.shell(serial, f"cat {DUMP_REMOTE}")
                if "<hierarchy" in xml_text:
                    last_exc = None
                    break
            except Exception as exc:
                last_exc = exc
        if last_exc is not None and "<hierarchy" not in xml_text:
            error = f"uiautomator dump failed: {last_exc}"
        nodes = parse_hierarchy(xml_text)
        shown, tree_text = compress(nodes, limit=self.tree_limit)
        package = shown[0].package if shown else ""
        try:
            screenshot = await self.adb.exec_out(serial, "screencap -p")
        except Exception as exc:
            screenshot = b""
            error = (error + f" screencap failed: {exc}").strip()
        scaled = scale_long_edge(screenshot, self.long_edge) if screenshot else b""
        return Observation(
            tree_text=tree_text,
            nodes=shown,
            screenshot=screenshot,
            screenshot_for_llm=scaled,
            package=package,
            raw_xml=xml_text,
            error=error,
            extra={"mode": mode},
        )

    async def _vision_only(self, serial: str) -> Observation:
        """Skip the accessibility dump. WeChat, Flutter, and many WebViews have no useful tree."""
        error = ""
        try:
            screenshot = await self.adb.exec_out(serial, "screencap -p")
        except Exception as exc:
            screenshot = b""
            error = f"screencap failed: {exc}"
        scaled = scale_long_edge(screenshot, self.long_edge) if screenshot else b""
        return Observation(
            tree_text="",
            nodes=[],
            screenshot=screenshot,
            screenshot_for_llm=scaled,
            error=error,
            extra={"mode": "vision-only"},
        )

    def apply_redaction(self, obs: Observation, *, enabled: bool) -> Observation:
        if not enabled or not obs.screenshot_for_llm:
            obs.redacted = False
            return obs
        obs.screenshot_for_llm = redact_png(obs.screenshot_for_llm)
        obs.redacted = True
        return obs
