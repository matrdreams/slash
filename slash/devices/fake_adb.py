"""In-memory adb used by unit tests and the scripted L0 loop. Never opens a socket."""

import base64

from slash.core.errors import AdbError

# 1x1 PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

DEFAULT_TREE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="com.android.settings" content-desc="" checkable="false" checked="false"
        clickable="false" enabled="true" focusable="false" focused="false" scrollable="false"
        long-clickable="false" password="false" selected="false" bounds="[0,0][720,1280]">
    <node index="0" text="设置" resource-id="com.android.settings:id/title"
          class="android.widget.TextView" package="com.android.settings" content-desc="设置"
          checkable="false" checked="false" clickable="true" enabled="true" focusable="true"
          focused="false" scrollable="false" long-clickable="false" password="false"
          selected="false" bounds="[40,200][680,280]" />
  </node>
</hierarchy>
"""


class FakeAdb:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.screenshot = TINY_PNG
        self.boot_completed = "1"
        self.reachable = True
        self.packages = "package:com.android.settings\n"
        self.hierarchy_xml = DEFAULT_TREE
        self.hierarchy_script: list[str] = []
        self.install_package: str | None = None
        self.pulled: dict[str, bytes] = {}

    def _check(self) -> None:
        if not self.reachable:
            raise AdbError("device offline")

    def _next_tree(self) -> str:
        if self.hierarchy_script:
            return self.hierarchy_script.pop(0)
        return self.hierarchy_xml

    async def connect(self, serial: str) -> str:
        self.calls.append(("connect", serial))
        self._check()
        return f"connected to {serial}"

    async def shell(self, serial: str, command: str) -> str:
        self.calls.append(("shell", serial, command))
        self._check()
        if command.startswith("getprop"):
            if "sys.boot_completed" in command:
                return self.boot_completed + "\n"
            return "\n"
        if "uiautomator dump" in command:
            return "UI hierchary dumped to: /sdcard/slash_uidump.xml\n"
        if "slash_uidump.xml" in command and command.startswith("cat"):
            return self._next_tree()
        if command.startswith("pm list packages"):
            return self.packages
        if command.startswith("df"):
            return (
                "Filesystem 1K-blocks Used Available Use% Mounted on\n"
                "/dev/block/data 1000000 1000 900000 1% /data\n"
            )
        if command.startswith("dumpsys activity activities"):
            return "mResumedActivity: com.android.settings/.Settings\n"
        return ""

    async def exec_out(self, serial: str, command: str) -> bytes:
        self.calls.append(("exec_out", serial, command))
        self._check()
        if "screencap" in command:
            return self.screenshot
        return b""

    async def install(
        self,
        serial: str,
        apk: str,
        *,
        grant: bool = True,
        multiple: list[str] | None = None,
    ) -> str:
        self.calls.append(("install", serial, apk, grant, tuple(multiple or ())))
        self._check()
        if self.install_package and f"package:{self.install_package}" not in self.packages:
            self.packages += f"package:{self.install_package}\n"
        return "Success\n"

    async def pull(self, serial: str, remote: str, local: str) -> str:
        self.calls.append(("pull", serial, remote, local))
        self._check()
        from pathlib import Path

        Path(local).write_bytes(self.pulled.get(remote, b"fake-mp4"))
        return f"pulled {remote}\n"

    async def getprop(self, serial: str, key: str) -> str:
        return (await self.shell(serial, f"getprop {key}")).strip()

    def shell_commands(self) -> list[str]:
        return [call[2] for call in self.calls if call[0] == "shell"]
