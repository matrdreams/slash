"""Device lifecycle: boot, provision, idle stop, snapshots, and signed APK installs."""

import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from slash.core.config import SlashConfig
from slash.core.errors import BootTimeoutError, ConflictError, NotFoundError, SignatureMismatchError
from slash.core.events import Event, EventBus
from slash.core.metrics import Metrics
from slash.core.models import DeviceCreate, DeviceOut, DeviceRuntimeState, DeviceState
from slash.devices.adb import SupportsAdb
from slash.devices.certs import (
    CertVerifier,
    assert_expected_cert,
    assert_registry_pin,
    file_sha256,
)
from slash.devices.snapshot import archive_tree, extract_tree
from slash.devices.specs import DeviceSpec, parse_mem_mb, parse_resolution, validate_device_name
from slash.store.db import Store
from slash.store.ids import new_id
from slash.store.tables import AppInstallRow, DeviceRow, SnapshotRow
from slash.store.timeutil import utcnow

# Component names follow upstream (ADBKeyBoard README, Mobilerun device-setup docs).
ADB_IME = "com.android.adbkeyboard/.AdbIME"
PORTAL_A11Y = "com.mobilerun.portal/com.mobilerun.portal.service.MobilerunAccessibilityService"

REQUIRED_PROVISION = (
    f"ime enable {ADB_IME}",
    f"ime set {ADB_IME}",
)
OPTIONAL_PROVISION = (
    f"settings put secure enabled_accessibility_services {PORTAL_A11Y}",
    "settings put secure accessibility_enabled 1",
    "settings put global window_animation_scale 0",
    "settings put global transition_animation_scale 0",
    "settings put global animator_duration_scale 0",
    "settings put system system_locales zh-CN",
    "setprop persist.sys.locale zh-CN",
    "setprop persist.sys.timezone Asia/Shanghai",
)

Sleeper = Callable[[float], Awaitable[None]]


class DeviceManager:
    def __init__(
        self,
        config: SlashConfig,
        store: Store,
        backend,
        adb: SupportsAdb,
        *,
        bus: EventBus | None = None,
        metrics: Metrics | None = None,
        cert_verifier: CertVerifier | None = None,
        pins: dict[str, str] | None = None,
        sleeper: Sleeper | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.config = config
        self.store = store
        self.backend = backend
        self.adb = adb
        self.bus = bus or EventBus()
        self.metrics = metrics or Metrics()
        self.cert_verifier = cert_verifier
        self.pins = pins or {}
        self.poll_interval = poll_interval

        async def _sleep(seconds: float) -> None:
            import asyncio

            await asyncio.sleep(seconds)

        self.sleeper = sleeper or _sleep

    def spec_from_row(self, row: DeviceRow) -> DeviceSpec:
        return DeviceSpec(
            id=row.id,
            name=row.name,
            image=row.image,
            android=row.android_version,
            width=row.width,
            height=row.height,
            dpi=row.dpi,
            fps=row.fps,
            gpu_mode=row.gpu_mode,
            mem=row.mem,
            cpus=row.cpus,
            dns=json.loads(row.dns_json or "[]"),
            use_memfd=row.use_memfd,
            adb_port=row.adb_port,
            data_path=row.data_path,
            proxy=row.proxy,
            binder_devices=list(self.config.devices.binder_devices),
            overlayfs=row.overlayfs,
            extra_props=json.loads(row.fingerprint_props or "{}"),
            seq=row.seq,
        )

    async def _remember(self, row: DeviceRow) -> DeviceSpec:
        spec = self.spec_from_row(row)
        await self.backend.ensure_spec(spec)
        return spec

    def to_out(self, row: DeviceRow, runtime: DeviceRuntimeState | None = None) -> DeviceOut:
        return DeviceOut(
            id=row.id,
            name=row.name,
            state=row.state,
            image=row.image,
            android=row.android_version,
            width=row.width,
            height=row.height,
            dpi=row.dpi,
            mem=row.mem,
            cpus=row.cpus,
            adb_port=row.adb_port,
            adb_serial=f"127.0.0.1:{row.adb_port}",
            data_path=row.data_path,
            proxy=row.proxy,
            runtime=runtime,
        )

    async def create(self, body: DeviceCreate, *, user_id: str) -> DeviceOut:
        name = validate_device_name(body.name)
        if self.store.get_device_by_name(name) is not None:
            raise ConflictError(f"device {name} already exists")
        defaults = self.config.devices.defaults
        width, height = defaults.width, defaults.height
        if body.resolution:
            width, height = parse_resolution(body.resolution)
        mem = body.mem or defaults.mem
        proxy_id = None
        if body.proxy:
            host, port_text = body.proxy.rsplit(":", 1)
            proxy_id = self.store.insert_proxy(host, int(port_text)).id
        seq = self.store.next_seq()
        row = DeviceRow(
            id=new_id(),
            user_id=user_id,
            name=name,
            backend=self.config.devices.backend,
            image=body.image or self.config.devices.default_image,
            android_version=body.android,
            width=width,
            height=height,
            dpi=body.dpi or defaults.dpi,
            fps=body.fps or defaults.fps,
            gpu_mode=body.gpu_mode or defaults.gpu_mode,
            mem=mem,
            mem_mb=parse_mem_mb(mem),
            cpus=body.cpus if body.cpus is not None else defaults.cpus,
            dns_json=json.dumps(defaults.dns),
            use_memfd=defaults.use_memfd,
            adb_port=self.config.devices.adb_port_base + seq,
            data_path=str(Path(self.config.devices.data_root) / name / "data"),
            proxy=body.proxy,
            proxy_profile_id=proxy_id,
            state=DeviceState.CREATED.value,
            fingerprint_props=json.dumps(body.fingerprint_props),
            seq=seq,
        )
        spec = self.spec_from_row(row)
        await self.backend.create(spec)
        saved = self.store.insert_device(row)
        self.store.audit("device.create", saved.id, {"name": name, "adb_port": saved.adb_port})
        self._refresh_running_gauge()
        return self.to_out(saved)

    async def list_devices(self) -> list[DeviceOut]:
        return [self.to_out(row) for row in self.store.list_devices()]

    async def get(self, device_id: str) -> DeviceOut:
        row = self.store.require_device(device_id)
        await self._remember(row)
        runtime = await self.backend.status(device_id)
        return self.to_out(row, runtime)

    async def start(self, device_id: str) -> DeviceOut:
        row = self.store.require_device(device_id)
        await self._remember(row)
        row.state = DeviceState.STARTING.value
        self.store.save_device(row)
        await self.backend.start(device_id)
        row = self.store.require_device(device_id)
        row.state = DeviceState.RUNNING.value
        row.last_active_at = utcnow()
        self.store.save_device(row)
        self._refresh_running_gauge()
        return self.to_out(self.store.require_device(device_id))

    async def stop(self, device_id: str, *, sync: bool = True) -> DeviceOut:
        row = self.store.require_device(device_id)
        await self._remember(row)
        if sync and row.state == DeviceState.RUNNING.value:
            serial = f"127.0.0.1:{row.adb_port}"
            try:
                await self.adb.shell(serial, "sync")
            except Exception:
                # A stopped or half-booted container may refuse sync. Still stop it.
                pass
        await self.backend.stop(device_id, sync=sync)
        row = self.store.require_device(device_id)
        row.state = DeviceState.STOPPED.value
        self.store.save_device(row)
        self._refresh_running_gauge()
        return self.to_out(row)

    async def restart(self, device_id: str) -> DeviceOut:
        await self.stop(device_id, sync=True)
        return await self.start(device_id)

    async def delete(self, device_id: str, *, keep_data: bool = True) -> None:
        row = self.store.require_device(device_id)
        await self._remember(row)
        if row.state == DeviceState.RUNNING.value:
            await self.stop(device_id, sync=True)
        await self.backend.delete(device_id, keep_data=keep_data)
        row = self.store.get_device(device_id)
        if row is not None:
            row.state = DeviceState.DELETED.value
            self.store.save_device(row)
        self.store.audit("device.delete", device_id, {"keep_data": keep_data})
        self._refresh_running_gauge()

    async def ensure_running(self, device_id: str) -> DeviceOut:
        row = self.store.require_device(device_id)
        await self._remember(row)
        serial = f"127.0.0.1:{row.adb_port}"
        started = time.monotonic()
        if row.state != DeviceState.RUNNING.value:
            await self.start(device_id)
        await self.adb.connect(serial)
        deadline = time.monotonic() + self.config.devices.boot_timeout_s
        booted = False
        while True:
            try:
                value = (await self.adb.shell(serial, "getprop sys.boot_completed")).strip()
            except Exception:
                value = ""
            if value == "1":
                booted = True
                break
            if time.monotonic() >= deadline:
                break
            await self.sleeper(self.poll_interval)
        if not booted:
            row = self.store.require_device(device_id)
            row.state = DeviceState.UNHEALTHY.value
            self.store.save_device(row)
            raise BootTimeoutError(
                f"device {row.name} did not report sys.boot_completed=1 "
                f"within {self.config.devices.boot_timeout_s}s"
            )
        self.metrics.set_gauge("slash_device_boot_seconds", time.monotonic() - started, device=row.name)
        row = self.store.require_device(device_id)
        if not row.provisioned:
            await self.provision(serial)
            row = self.store.require_device(device_id)
            row.provisioned = True
            self.store.save_device(row)
        self.touch(device_id)
        return self.to_out(self.store.require_device(device_id))

    async def provision(self, serial: str) -> None:
        for command in REQUIRED_PROVISION:
            await self.adb.shell(serial, command)
        for command in OPTIONAL_PROVISION:
            try:
                await self.adb.shell(serial, command)
            except Exception:
                continue

    def touch(self, device_id: str, when: datetime | None = None) -> None:
        row = self.store.require_device(device_id)
        row.last_active_at = when or utcnow()
        self.store.save_device(row)

    async def reap_idle(self, now: datetime | None = None) -> list[str]:
        moment = now or utcnow()
        timeout = timedelta(minutes=self.config.devices.idle_timeout_min)
        stopped: list[str] = []
        for row in self.store.list_devices():
            if row.state != DeviceState.RUNNING.value or row.last_active_at is None:
                continue
            if self.store.active_task_for_device(row.id) is not None:
                continue
            if moment - row.last_active_at < timeout:
                continue
            await self.stop(row.id, sync=True)
            stopped.append(row.id)
            self.store.audit("device.idle_stop", row.id, {"idle_timeout_min": self.config.devices.idle_timeout_min})
        return stopped

    async def snapshot(self, device_id: str, *, note: str = "") -> SnapshotRow:
        row = self.store.require_device(device_id)
        was_running = row.state == DeviceState.RUNNING.value
        if was_running:
            await self.stop(device_id, sync=True)
        data = Path(row.data_path)
        snapshot_id = new_id()
        dest = Path(self.config.devices.data_root) / row.name / "snapshots" / f"{snapshot_id}.tar.gz"
        size = archive_tree(data, dest)
        saved = self.store.insert_snapshot(
            SnapshotRow(
                id=snapshot_id,
                device_id=device_id,
                path=str(dest),
                size_bytes=size,
                encrypted=False,
                note=note,
            )
        )
        self.store.audit("device.snapshot", device_id, {"snapshot_id": snapshot_id, "bytes": size})
        if was_running:
            await self.start(device_id)
        return saved

    async def restore(self, device_id: str, snapshot_id: str) -> SnapshotRow:
        row = self.store.require_device(device_id)
        snap = self.store.get_snapshot(snapshot_id)
        if snap is None or snap.device_id != device_id:
            raise NotFoundError(f"snapshot {snapshot_id} not found")
        if row.state == DeviceState.RUNNING.value:
            raise ConflictError("stop the device before restoring a snapshot")
        extract_tree(Path(snap.path), Path(row.data_path))
        self.store.audit("device.restore", device_id, {"snapshot_id": snapshot_id})
        return snap

    async def install_app(
        self,
        device_id: str,
        apk: Path,
        *,
        expected_cert_sha256: str,
        sha256: str | None = None,
        package: str | None = None,
        splits: list[Path] | None = None,
    ) -> AppInstallRow:
        if self.cert_verifier is None:
            raise SignatureMismatchError("no certificate verifier is configured")
        row = self.store.require_device(device_id)
        if row.state != DeviceState.RUNNING.value:
            raise ConflictError("device must be running to install an app")
        digest = file_sha256(apk)
        if sha256 and digest != sha256.lower():
            raise SignatureMismatchError(f"apk sha256 mismatch: expected {sha256.lower()} got {digest}")
        cert = self.cert_verifier.fingerprint(apk)
        cert = assert_expected_cert(cert, expected_cert_sha256)
        assert_registry_pin(package, cert, self.pins)
        serial = f"127.0.0.1:{row.adb_port}"
        before = set(await self.list_packages(device_id))
        extras = [str(path) for path in (splits or [])]
        await self.adb.install(serial, str(apk), grant=True, multiple=[str(apk), *extras] if extras else None)
        after = set(await self.list_packages(device_id))
        installed = package or ""
        new_packages = sorted(after - before)
        if not installed and len(new_packages) == 1:
            installed = new_packages[0]
        saved = self.store.insert_app(
            AppInstallRow(
                id=new_id(),
                device_id=device_id,
                package=installed,
                apk_sha256=digest,
                cert_sha256=cert,
            )
        )
        self.store.audit("device.install", device_id, {"package": installed, "sha256": digest})
        return saved

    async def list_packages(self, device_id: str) -> list[str]:
        row = self.store.require_device(device_id)
        if row.state != DeviceState.RUNNING.value:
            return []
        text = await self.adb.shell(f"127.0.0.1:{row.adb_port}", "pm list packages -3")
        packages = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.split(":", 1)[1])
        return packages

    async def screenshot(self, device_id: str) -> bytes:
        row = self.store.require_device(device_id)
        if row.state != DeviceState.RUNNING.value:
            raise ConflictError("device is not running")
        return await self.adb.exec_out(f"127.0.0.1:{row.adb_port}", "screencap -p")

    async def logs(self, device_id: str, tail: int = 200) -> str:
        row = self.store.require_device(device_id)
        await self._remember(row)
        return await self.backend.logs(device_id, tail=tail)

    def _refresh_running_gauge(self) -> None:
        self.metrics.set_gauge("slash_devices_running", float(self.store.count_state(DeviceState.RUNNING.value)))
