"""Audit recording during a takeover.

`screenrecord` stops itself after 180 seconds, so a longer takeover is several
files: /sdcard/slash-takeover-<id>-<n>.mp4. SIGINT finishes the current file.
"""

import asyncio
import contextlib
import time
from pathlib import Path

from slash.devices.adb import SupportsAdb

SEGMENT_SECONDS = 180


class Recorder:
    def __init__(self, adb: SupportsAdb) -> None:
        self.adb = adb
        self._tasks: dict[str, asyncio.Task] = {}
        self._segments: dict[str, list[str]] = {}

    def remote_path(self, takeover_id: str, index: int = 0) -> str:
        return f"/sdcard/slash-takeover-{takeover_id}-{index}.mp4"

    def start(self, serial: str, takeover_id: str) -> None:
        self._segments[takeover_id] = []

        async def _run() -> None:
            index = 0
            while True:
                remote = self.remote_path(takeover_id, index)
                self._segments.setdefault(takeover_id, []).append(remote)
                started = time.monotonic()
                try:
                    await self.adb.shell(
                        serial,
                        f"screenrecord --time-limit {SEGMENT_SECONDS} {remote}",
                    )
                except Exception:
                    return
                # A real screenrecord blocks until the time limit or a signal.
                # An immediate return means the device rejected the command.
                if time.monotonic() - started < 1.0:
                    return
                index += 1

        self._tasks[takeover_id] = asyncio.create_task(_run())

    async def stop(self, serial: str, takeover_id: str, dest: Path) -> str:
        task = self._tasks.pop(takeover_id, None)
        try:
            await self.adb.shell(serial, "pkill -INT screenrecord")
        except Exception:
            pass
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        dest.parent.mkdir(parents=True, exist_ok=True)
        remotes = self._segments.pop(takeover_id, [])
        if not remotes:
            remotes = [self.remote_path(takeover_id, 0)]
        saved = ""
        for index, remote in enumerate(remotes):
            target = dest if index == 0 else dest.with_name(f"{dest.stem}-{index}{dest.suffix}")
            try:
                await self.adb.pull(serial, remote, str(target))
            except Exception:
                continue
            if index == 0:
                saved = str(target)
            elif not saved:
                saved = str(target)
        if not saved:
            await self.adb.pull(serial, remotes[0], str(dest))
            saved = str(dest)
        return saved
