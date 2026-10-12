"""USB or already-connected adb devices. No container is created or stopped."""

from slash.core.errors import SlashError
from slash.core.models import DeviceRuntimeState
from slash.devices.specs import DeviceSpec


class PhysicalBackend:
    """Same DeviceBackend surface as compose, for a phone that is already on adb.

    start and stop do not power the handset. They only mark the spec known so
    the manager can poll sys.boot_completed on the configured serial.
    """

    uses_backend_serial = True

    def __init__(self, serials: dict[str, str] | None = None) -> None:
        self.serials = dict(serials or {})
        self.specs: dict[str, DeviceSpec] = {}

    def _require(self, device_id: str) -> DeviceSpec:
        spec = self.specs.get(device_id)
        if spec is None:
            raise SlashError(f"physical device {device_id} is not registered")
        return spec

    async def ensure_spec(self, spec: DeviceSpec) -> None:
        self.specs[spec.id] = spec

    async def create(self, spec: DeviceSpec) -> str:
        await self.ensure_spec(spec)
        return spec.name

    async def start(self, device_id: str) -> None:
        self._require(device_id)

    async def stop(self, device_id: str, sync: bool = True) -> None:
        self._require(device_id)

    async def delete(self, device_id: str, keep_data: bool = True) -> None:
        self.specs.pop(device_id, None)

    async def status(self, device_id: str) -> DeviceRuntimeState:
        self._require(device_id)
        return DeviceRuntimeState(state="RUNNING", running=True, detail="physical adb")

    async def adb_serial(self, device_id: str) -> str:
        spec = self._require(device_id)
        serial = self.serials.get(spec.name, "").strip()
        return serial or spec.adb_serial()

    async def logs(self, device_id: str, tail: int = 200) -> str:
        self._require(device_id)
        return "physical backend has no container logs\n"
