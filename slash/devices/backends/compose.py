"""docker compose backend.

The manager writes a complete override file and runs
`docker compose -f phones.override.yml up -d phone-<name>`.
ADB ports in that file are 127.0.0.1 only.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml

from slash.core.errors import SlashError
from slash.core.models import DeviceRuntimeState
from slash.devices.adb import run_cmd_bytes
from slash.devices.specs import DeviceSpec, service_dict

Runner = Callable[[list[str], float | None], Awaitable[tuple[int, bytes, bytes]]]


def render_override(specs: list[DeviceSpec]) -> str:
    document: dict = {"services": {}, "networks": {}}
    for spec in specs:
        document["services"][spec.service_name()] = service_dict(spec)
        document["networks"][f"net-{spec.name}"] = {}
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if "0.0.0.0:" in text:
        raise SlashError("refusing to write a compose file that publishes on 0.0.0.0")
    return text


class ComposeBackend:
    def __init__(self, override_path: str | Path, runner: Runner | None = None) -> None:
        self.override_path = Path(override_path)
        self.runner = runner or run_cmd_bytes
        self.specs: dict[str, DeviceSpec] = {}

    def _require(self, device_id: str) -> DeviceSpec:
        spec = self.specs.get(device_id)
        if spec is None:
            raise SlashError(f"compose device {device_id} is not registered")
        return spec

    def write_override(self) -> None:
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        text = render_override(list(self.specs.values()))
        self.override_path.write_text(text, encoding="utf-8")

    async def _run(self, args: list[str]) -> str:
        code, out, err = await self.runner(args, 180)
        text = out.decode(errors="replace") + err.decode(errors="replace")
        if code != 0:
            raise SlashError(text.strip() or f"command failed: {' '.join(args)}")
        return text

    def _compose(self, *args: str) -> list[str]:
        return ["docker", "compose", "-f", str(self.override_path), *args]

    async def ensure_spec(self, spec: DeviceSpec) -> None:
        self.specs[spec.id] = spec

    async def create(self, spec: DeviceSpec) -> str:
        await self.ensure_spec(spec)
        Path(spec.data_path).mkdir(parents=True, exist_ok=True)
        self.write_override()
        return spec.service_name()

    async def start(self, device_id: str) -> None:
        spec = self._require(device_id)
        self.write_override()
        await self._run(self._compose("up", "-d", spec.service_name()))

    async def stop(self, device_id: str, sync: bool = True) -> None:
        spec = self._require(device_id)
        self.write_override()
        await self._run(self._compose("stop", spec.service_name()))

    async def delete(self, device_id: str, keep_data: bool = True) -> None:
        spec = self._require(device_id)
        self.write_override()
        await self._run(self._compose("rm", "-f", "-s", spec.service_name()))
        self.specs.pop(device_id, None)
        self.write_override()
        if not keep_data:
            path = Path(spec.data_path)
            if path.exists():
                import shutil

                shutil.rmtree(path)

    async def status(self, device_id: str) -> DeviceRuntimeState:
        spec = self._require(device_id)
        code, out, err = await self.runner(
            self._compose("ps", "--status", "running", "--format", "{{.Service}}"),
            60,
        )
        if code != 0:
            return DeviceRuntimeState(state="STOPPED", running=False, detail=err.decode(errors="replace"))
        running = spec.service_name() in out.decode(errors="replace").split()
        return DeviceRuntimeState(
            state="RUNNING" if running else "STOPPED",
            running=running,
            detail=spec.service_name(),
        )

    async def adb_serial(self, device_id: str) -> str:
        return self._require(device_id).adb_serial()

    async def logs(self, device_id: str, tail: int = 200) -> str:
        spec = self._require(device_id)
        return await self._run(self._compose("logs", "--tail", str(tail), spec.service_name()))
