"""uiautomator2-backed device ops: fast hierarchy dumps, checkers, Chinese input, app mgmt.

uiautomator2 is imported lazily so the module (and tests) work without a device.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass
class U2Device:
    serial: str
    _d: Any = None

    @classmethod
    def connect(cls, serial: str, *, factory=None) -> U2Device:
        if factory is None:
            import uiautomator2 as u2

            factory = u2.connect
        return cls(serial=serial, _d=factory(serial))

    @property
    def raw(self):
        return self._d

    def dump_hierarchy(self, compressed: bool = False) -> str:
        return self._d.dump_hierarchy(compressed=compressed)

    def screenshot_png(self) -> bytes:
        import io

        image = self._d.screenshot()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def send_keys(self, text: str, clear: bool = False) -> None:
        self._d.send_keys(text, clear=clear)

    def app_start(self, package: str, activity: str | None = None, stop: bool = False) -> None:
        self._d.app_start(package, activity=activity, stop=stop)

    def app_stop(self, package: str) -> None:
        self._d.app_stop(package)

    def current_app(self) -> dict:
        return self._d.app_current()

    def shell(self, cmd: str) -> str:
        out = self._d.shell(cmd)
        return getattr(out, "output", out) or ""

    # ---- settings / checker helpers ----
    def get_setting(self, namespace: str, key: str) -> str:
        return self.shell(f"settings get {namespace} {key}").strip()

    def find_text(self, *, resource_id: str | None = None, text: str | None = None) -> list[str]:
        return find_in_hierarchy(self.dump_hierarchy(), resource_id=resource_id, text=text)

    def has_text(self, pattern: str) -> bool:
        rx = re.compile(pattern)
        return any(rx.search(t) for t in find_in_hierarchy(self.dump_hierarchy()))


def find_in_hierarchy(xml: str, *, resource_id: str | None = None, text: str | None = None) -> list[str]:
    """Return text values of nodes matching a resource-id (or its suffix) and/or exact text."""
    out: list[str] = []
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        rid = node.get("resource-id", "")
        value = node.get("text", "")
        if resource_id and not (rid == resource_id or rid.endswith(":id/" + resource_id)):
            continue
        if text is not None and value != text:
            continue
        if value or resource_id:
            out.append(value)
    return out


def check_search_text(dev: U2Device, expected: str) -> bool:
    """Settings search box contains `expected` (checker used by e2e)."""
    return expected in dev.find_text(resource_id="search_src_text")
