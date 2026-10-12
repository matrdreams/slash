"""Execute one action through adb. Chinese text goes through ADBKeyBoard base64."""

import asyncio
import base64
import re
import shlex
from collections.abc import Awaitable, Callable

from slash.agent.actions import (
    KEYCODES,
    Action,
    AskHuman,
    Done,
    KeyAction,
    Launch,
    LongPress,
    ScreenshotAction,
    Swipe,
    Tap,
    TypeText,
    Wait,
)
from slash.agent.tree import UINode, center, find_node
from slash.core.errors import AdbError, PolicyViolation
from slash.devices.adb import SupportsAdb

ADB_IME = "com.android.adbkeyboard/.AdbIME"
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

Sleeper = Callable[[float], Awaitable[None]]


def b64_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def input_broadcast(text: str) -> str:
    encoded = shlex.quote(b64_text(text))
    return f"am broadcast -a ADB_INPUT_B64 --es msg {encoded}"


class Actuator:
    def __init__(self, adb: SupportsAdb, sleeper: Sleeper | None = None) -> None:
        self.adb = adb

        async def _sleep(seconds: float) -> None:
            await asyncio.sleep(seconds)

        self.sleeper = sleeper or _sleep

    async def execute(
        self,
        serial: str,
        action: Action,
        nodes: list[UINode],
        *,
        width: int,
        height: int,
    ) -> None:
        if isinstance(action, (AskHuman, Done, ScreenshotAction)):
            return
        if isinstance(action, Tap):
            x, y = self._point(action.element_id, action.x, action.y, nodes, width, height)
            await self.adb.shell(serial, f"input tap {x} {y}")
            return
        if isinstance(action, LongPress):
            x, y = self._point(action.element_id, action.x, action.y, nodes, width, height)
            await self.adb.shell(serial, f"input swipe {x} {y} {x} {y} {action.ms}")
            return
        if isinstance(action, Swipe):
            self._inside(action.x1, action.y1, width, height)
            self._inside(action.x2, action.y2, width, height)
            await self.adb.shell(
                serial,
                f"input swipe {action.x1} {action.y1} {action.x2} {action.y2} {action.ms}",
            )
            return
        if isinstance(action, TypeText):
            if action.element_id is not None:
                x, y = self._point(action.element_id, None, None, nodes, width, height)
                await self.adb.shell(serial, f"input tap {x} {y}")
            await self.adb.shell(serial, f"ime set {ADB_IME}")
            await self.adb.shell(serial, input_broadcast(action.text))
            if action.submit:
                await self.adb.shell(serial, f"input keyevent {KEYCODES['ENTER']}")
            return
        if isinstance(action, KeyAction):
            await self.adb.shell(serial, f"input keyevent {KEYCODES[action.key]}")
            return
        if isinstance(action, Launch):
            if not _PACKAGE.fullmatch(action.package):
                raise PolicyViolation(f"refusing to launch invalid package {action.package!r}")
            quoted = shlex.quote(action.package)
            await self.adb.shell(serial, f"monkey -p {quoted} -c android.intent.category.LAUNCHER 1")
            return
        if isinstance(action, Wait):
            await self.sleeper(max(action.ms, 0) / 1000)
            return
        raise PolicyViolation(f"unsupported action {action}")

    def _point(
        self,
        element_id: int | None,
        x: int | None,
        y: int | None,
        nodes: list[UINode],
        width: int,
        height: int,
    ) -> tuple[int, int]:
        if element_id is not None:
            node = find_node(nodes, element_id)
            if node is None:
                raise PolicyViolation(f"element {element_id} is not in the current tree")
            x, y = center(node)
        if x is None or y is None:
            raise PolicyViolation("action has no coordinates")
        self._inside(x, y, width, height)
        return x, y

    @staticmethod
    def _inside(x: int, y: int, width: int, height: int) -> None:
        if x < 0 or y < 0 or x > width or y > height:
            raise PolicyViolation(f"coordinate {(x, y)} is outside {width}x{height}")
