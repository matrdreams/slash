"""In-process Redroid stand-in. Data lives on a real directory so snapshots work."""

import shutil
from pathlib import Path

from slash.core.errors import NotFoundError
from slash.core.models import DeviceRuntimeState
from slash.devices.specs import DeviceSpec


class FakeBackend:
    def __init__(self) -> None:
        self.specs: dict[str, DeviceSpec] = {}
        self.running: dict[str, bool] = {}
        self.oom: dict[str, bool] = {}
        self.ops: list[tuple] = []
        self.logs_text: dict[str, str] = {}

    def _require(self, device_id: str) -> DeviceSpec:
        spec = self.specs.get(device_id)
        if spec is None:
            raise NotFoundError(f"fake device {device_id} is not registered")
        return spec

    async def ensure_spec(self, spec: DeviceSpec) -> None:
        self.specs[spec.id] = spec
        self.running.setdefault(spec.id, False)
        self.oom.setdefault(spec.id, False)

    async def create(self, spec: DeviceSpec) -> str:
        await self.ensure_spec(spec)
        path = Path(spec.data_path)
        path.mkdir(parents=True, exist_ok=True)
        marker = path / "data.txt"
        if not marker.exists():
            marker.write_text("fresh\n", encoding="utf-8")
        self.ops.append(("create", spec.id, spec.adb_serial()))
        return spec.container_name()

    async def start(self, device_id: str) -> None:
        self._require(device_id)
        self.running[device_id] = True
        self.ops.append(("start", device_id))

    async def stop(self, device_id: str, sync: bool = True) -> None:
        self._require(device_id)
        self.running[device_id] = False
        self.ops.append(("stop", device_id, sync))

    async def delete(self, device_id: str, keep_data: bool = True) -> None:
        spec = self._require(device_id)
        self.running[device_id] = False
        self.ops.append(("delete", device_id, keep_data))
        if not keep_data:
            path = Path(spec.data_path)
            if path.exists():
                shutil.rmtree(path)
        self.specs.pop(device_id, None)

    async def status(self, device_id: str) -> DeviceRuntimeState:
        spec = self._require(device_id)
        running = self.running.get(device_id, False)
        return DeviceRuntimeState(
            state="RUNNING" if running else "STOPPED",
            running=running,
            boot_completed=True if running else False,
            oom=self.oom.get(device_id, False),
            detail=spec.container_name(),
        )

    async def adb_serial(self, device_id: str) -> str:
        return self._require(device_id).adb_serial()

    async def logs(self, device_id: str, tail: int = 200) -> str:
        self._require(device_id)
        text = self.logs_text.get(device_id, "fake log\n")
        lines = text.splitlines()
        return "\n".join(lines[-tail:])
