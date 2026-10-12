"""Async adb wrapper. Commands are argument lists, never a shell on the host."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from slash.core.errors import AdbError

Runner = Callable[[list[str], float | None], Awaitable[tuple[int, bytes, bytes]]]


async def run_cmd_bytes(args: list[str], timeout: float | None = 120) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise AdbError(f"timeout running {' '.join(args)}") from None
    return proc.returncode or 0, out, err


class AdbClient:
    """Talks to a real adb binary. Tests use FakeAdb instead."""

    def __init__(self, adb_bin: str = "adb", runner: Runner | None = None, timeout: float = 120) -> None:
        self.adb_bin = adb_bin
        self.runner = runner or run_cmd_bytes
        self.timeout = timeout

    async def connect(self, serial: str) -> str:
        code, out, err = await self.runner([self.adb_bin, "connect", serial], self.timeout)
        text = out.decode(errors="replace") + err.decode(errors="replace")
        if code != 0 and "connected" not in text and "already" not in text:
            raise AdbError(text.strip() or f"adb connect {serial} failed")
        return text

    async def shell(self, serial: str, command: str) -> str:
        code, out, err = await self.runner(
            [self.adb_bin, "-s", serial, "shell", command],
            self.timeout,
        )
        if code != 0:
            message = err.decode(errors="replace") or out.decode(errors="replace")
            raise AdbError(message.strip() or f"adb shell failed: {command}")
        return out.decode(errors="replace")

    async def exec_out(self, serial: str, command: str) -> bytes:
        code, out, err = await self.runner(
            [self.adb_bin, "-s", serial, "exec-out", *command.split()],
            self.timeout,
        )
        if code != 0:
            raise AdbError(err.decode(errors="replace") or f"adb exec-out failed: {command}")
        return out

    async def install(
        self,
        serial: str,
        apk: str,
        *,
        grant: bool = True,
        multiple: list[str] | None = None,
    ) -> str:
        if multiple:
            args = [self.adb_bin, "-s", serial, "install-multiple", "-r"]
            if grant:
                args.append("-g")
            args.extend(multiple)
        else:
            args = [self.adb_bin, "-s", serial, "install", "-r"]
            if grant:
                args.append("-g")
            args.append(apk)
        code, out, err = await self.runner(args, self.timeout)
        text = out.decode(errors="replace") + err.decode(errors="replace")
        if code != 0 or "Failure" in text:
            raise AdbError(text.strip() or "adb install failed")
        return text

    async def pull(self, serial: str, remote: str, local: str) -> str:
        code, out, err = await self.runner(
            [self.adb_bin, "-s", serial, "pull", remote, local],
            self.timeout,
        )
        text = out.decode(errors="replace") + err.decode(errors="replace")
        if code != 0:
            raise AdbError(text.strip() or f"adb pull {remote} failed")
        return text

    async def getprop(self, serial: str, key: str) -> str:
        return (await self.shell(serial, f"getprop {key}")).strip()


class SupportsAdb(Protocol):
    async def connect(self, serial: str) -> str: ...

    async def shell(self, serial: str, command: str) -> str: ...

    async def exec_out(self, serial: str, command: str) -> bytes: ...

    async def install(
        self,
        serial: str,
        apk: str,
        *,
        grant: bool = True,
        multiple: list[str] | None = None,
    ) -> str: ...

    async def pull(self, serial: str, remote: str, local: str) -> str: ...

    async def getprop(self, serial: str, key: str) -> str: ...
