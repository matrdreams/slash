"""Periodic health check. Three failures in a row restart the device."""

from slash.core.errors import AdbError
from slash.core.events import Event, EventBus
from slash.devices.adb import SupportsAdb


def parse_df(output: str) -> dict[str, int | str]:
    for line in reversed(output.splitlines()):
        parts = line.split()
        if len(parts) >= 6 and parts[1].isdigit():
            return {
                "total_kb": int(parts[1]),
                "used_kb": int(parts[2]),
                "available_kb": int(parts[3]),
                "used_percent": int(parts[4].rstrip("%")),
                "mount": parts[5],
            }
    return {}


class HealthMonitor:
    def __init__(self, manager, adb: SupportsAdb, bus: EventBus | None = None, strike_limit: int = 3) -> None:
        self.manager = manager
        self.adb = adb
        self.bus = bus or EventBus()
        self.strike_limit = strike_limit
        self.failures: dict[str, int] = {}

    async def check(self, device_id: str) -> dict:
        device = self.manager.store.require_device(device_id)
        if device.state != "RUNNING":
            return {
                "device_id": device_id,
                "adb": False,
                "boot_completed": False,
                "oom": False,
                "storage": {},
                "healthy": True,
                "failures": self.failures.get(device_id, 0),
                "reasons": [],
                "state": device.state,
            }
        await self.manager._remember(device)
        serial = await self.manager.backend.adb_serial(device_id)
        runtime = await self.manager.backend.status(device_id)
        report: dict = {
            "device_id": device_id,
            "adb": False,
            "boot_completed": False,
            "oom": runtime.oom,
            "storage": {},
            "healthy": False,
            "failures": self.failures.get(device_id, 0),
        }
        reasons: list[str] = []
        if not runtime.running:
            reasons.append("container is not running")
        else:
            try:
                boot = await self.adb.getprop(serial, "sys.boot_completed")
                report["adb"] = True
                report["boot_completed"] = boot.strip() == "1"
                if not report["boot_completed"]:
                    reasons.append("boot_completed is not 1")
                df_text = await self.adb.shell(serial, "df /data")
                storage = parse_df(df_text)
                report["storage"] = storage
                available = int(storage.get("available_kb") or 0)
                if storage and available < 200_000:
                    reasons.append(f"/data is low on space ({available}K free)")
            except AdbError as exc:
                reasons.append(f"adb unreachable: {exc}")
        if runtime.oom:
            reasons.append("container was OOMKilled")
        report["reasons"] = reasons
        report["healthy"] = not reasons
        if report["healthy"]:
            self.failures[device_id] = 0
        else:
            self.failures[device_id] = self.failures.get(device_id, 0) + 1
            self.bus.publish(
                Event(
                    kind="device.unhealthy",
                    target=device_id,
                    detail={"reasons": reasons, "failures": self.failures[device_id]},
                )
            )
            if self.failures[device_id] >= self.strike_limit:
                await self.manager.restart(device_id)
                self.failures[device_id] = 0
        report["failures"] = self.failures.get(device_id, 0)
        return report

    async def check_running(self) -> list[dict]:
        reports = []
        for device in self.manager.store.list_devices():
            if device.state == "RUNNING":
                reports.append(await self.check(device.id))
        return reports
