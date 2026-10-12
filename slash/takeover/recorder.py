"""Audit recording during a takeover. screenrecord segments are at most 180 seconds."""

import asyncio
from pathlib import Path

from slash.devices.adb import SupportsAdb

SEGMENT_SECONDS = 180


class Recorder:
    def __init__(self, adb: SupportsAdb) -> None:
        self.adb = adb
        self._tasks: dict[str, asyncio.Task] = {}

    def remote_path(self, takeover_id: str) -> str:
        return f"/sdcard/slash-takeover-{takeover_id}.mp4"

    def start(self, serial: str, takeover_id: str) -> None:
        remote = self.remote_path(takeover_id)
        command = f"screenrecord --time-limit {SEGMENT_SECONDS} {remote}"

        async def _run() -> None:
            try:
                await self.adb.shell(serial, command)
            except Exception:
                return

        self._tasks[takeover_id] = asyncio.create_task(_run())

    async def stop(self, serial: str, takeover_id: str, dest: Path) -> str:
        task = self._tasks.pop(takeover_id, None)
        try:
            await self.adb.shell(serial, "pkill -INT screenrecord")
        except Exception:
            pass
        if task is not None:
            task.cancel()
        dest.parent.mkdir(parents=True, exist_ok=True)
        await self.adb.pull(serial, self.remote_path(takeover_id), str(dest))
        return str(dest)
