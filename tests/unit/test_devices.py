import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from slash.core.errors import BootTimeoutError, ConflictError, SignatureMismatchError
from slash.core.models import DeviceCreate, DeviceState
from slash.devices.backends.compose import render_override
from slash.devices.backends.docker_api import docker_create_args
from slash.devices.backends.k8s import render_manifest
from slash.devices.snapshot import archive_tree, extract_tree
from slash.devices.specs import DeviceSpec, boot_args
from slash.store.timeutil import utcnow


def _spec(tmp_path: Path) -> DeviceSpec:
    return DeviceSpec(
        id="d1",
        name="u1",
        image="redroid/redroid:12.0.0-latest",
        adb_port=5601,
        data_path=str(tmp_path / "data"),
        dns=["223.5.5.5"],
        use_memfd=True,
    )


def test_publish_address_is_loopback_only(tmp_path):
    spec = _spec(tmp_path)
    text = render_override([spec])
    assert "0.0.0.0" not in text
    assert "127.0.0.1:5601:5555" in text
    args = docker_create_args(spec)
    assert "127.0.0.1:5601:5555" in args
    assert "0.0.0.0:5601:5555" not in args
    assert "--privileged" in args
    assert "androidboot.redroid_net_dns1=223.5.5.5" in boot_args(spec)
    assert "androidboot.use_memfd=true" in boot_args(spec)
    manifest = render_manifest(spec)
    assert manifest["statefulset"]["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"]
    assert manifest["service"]["spec"]["type"] == "ClusterIP"
    assert manifest["statefulset"]["spec"]["template"]["spec"]["nodeSelector"]["slash.dev/binder"] == "true"


def test_checked_in_compose_files_bind_loopback():
    root = Path(__file__).resolve().parents[2] / "deploy" / "compose"
    for name in ("docker-compose.yml", "docker-compose.multi.yml", "phones.override.example.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "127.0.0.1:" in text
        assert "0.0.0.0:" not in text


def test_create_start_stop_delete_three_devices(world):
    ctx = world()

    async def scenario():
        created = []
        for name in ("u1", "u2", "u3"):
            created.append(await ctx.manager.create(DeviceCreate(name=name), user_id=ctx.user_id))
        assert [item.adb_port for item in created] == [5601, 5602, 5603]
        assert all(item.adb_serial.startswith("127.0.0.1:") for item in created)
        for item in created:
            started = await ctx.manager.ensure_running(item.id)
            assert started.state == DeviceState.RUNNING.value
        commands = ctx.adb.shell_commands()
        assert any(command.startswith("ime set com.android.adbkeyboard/.AdbIME") for command in commands)
        assert any("window_animation_scale 0" in command for command in commands)
        assert any("zh-CN" in command for command in commands)
        for item in created:
            await ctx.manager.stop(item.id)
            await ctx.manager.delete(item.id, keep_data=True)
        assert await ctx.manager.list_devices() == []

    import asyncio

    asyncio.run(scenario())


def test_snapshot_restore_keeps_files(world, tmp_path):
    ctx = world()

    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        await ctx.manager.start(device.id)
        data = Path(device.data_path)
        secret = data / "data" / "com.app" / "auth.db"
        secret.parent.mkdir(parents=True)
        secret.write_text("session-token", encoding="utf-8")
        snap = await ctx.manager.snapshot(device.id, note="login")
        secret.write_text("wiped", encoding="utf-8")
        await ctx.manager.stop(device.id)
        await ctx.manager.restore(device.id, snap.id)
        assert secret.read_text(encoding="utf-8") == "session-token"
        with pytest.raises(ConflictError):
            await ctx.manager.start(device.id)
            await ctx.manager.restore(device.id, snap.id)

    import asyncio

    asyncio.run(scenario())


def test_archive_roundtrip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.txt").write_text("hello", encoding="utf-8")
    archive = tmp_path / "snap.tar.gz"
    archive_tree(src, archive)
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "note.txt").write_text("changed", encoding="utf-8")
    extract_tree(archive, dest)
    assert (dest / "note.txt").read_text(encoding="utf-8") == "hello"


def test_idle_reaper_stops_only_idle_devices(world):
    ctx = world(idle_timeout_min=30)

    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        await ctx.manager.start(device.id)
        row = ctx.store.require_device(device.id)
        row.last_active_at = utcnow() - timedelta(minutes=31)
        ctx.store.save_device(row)
        stopped = await ctx.manager.reap_idle(now=utcnow())
        assert stopped == [device.id]
        assert ctx.store.require_device(device.id).state == DeviceState.STOPPED.value
        assert "sync" in ctx.adb.shell_commands()

        other = await ctx.manager.create(DeviceCreate(name="u2"), user_id=ctx.user_id)
        await ctx.manager.start(other.id)
        busy = ctx.store.require_device(other.id)
        busy.last_active_at = utcnow() - timedelta(minutes=90)
        ctx.store.save_device(busy)
        from slash.core.models import TaskStatus
        from slash.store.ids import new_id
        from slash.store.tables import TaskRow

        ctx.store.insert_task(
            TaskRow(
                id=new_id(),
                device_id=other.id,
                goal="still working",
                status=TaskStatus.RUNNING.value,
                provider="fake",
                mode="tree",
            )
        )
        assert await ctx.manager.reap_idle(now=utcnow()) == []

    import asyncio

    asyncio.run(scenario())


def test_boot_timeout(world):
    ctx = world(boot_timeout_s=0)
    ctx.adb.boot_completed = "0"

    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        with pytest.raises(BootTimeoutError):
            await ctx.manager.ensure_running(device.id)
        assert ctx.store.require_device(device.id).state == DeviceState.UNHEALTHY.value

    import asyncio

    asyncio.run(scenario())


def test_signature_check_before_install(world, tmp_path):
    ctx = world()
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"fake-apk")
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()

    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        await ctx.manager.start(device.id)
        with pytest.raises(SignatureMismatchError):
            await ctx.manager.install_app(
                device.id,
                apk,
                expected_cert_sha256="ffff",
                sha256=digest,
                package="com.example.app",
            )
        assert not any(call[0] == "install" for call in ctx.adb.calls)
        ctx.adb.install_package = "com.example.app"
        ctx.verifier.fingerprint_value = "abcd"
        saved = await ctx.manager.install_app(
            device.id,
            apk,
            expected_cert_sha256="ab:cd",
            sha256=digest,
            package="com.example.app",
        )
        assert saved.package == "com.example.app"
        assert saved.cert_sha256 == "abcd"
        assert any(call[0] == "install" and call[3] is True for call in ctx.adb.calls)

    import asyncio

    asyncio.run(scenario())


def test_health_restarts_after_three_failures(world):
    ctx = world()

    async def scenario():
        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        await ctx.manager.start(device.id)
        ctx.adb.reachable = False
        await ctx.health.check(device.id)
        await ctx.health.check(device.id)
        report = await ctx.health.check(device.id)
        assert report["adb"] is False
        assert any(op[0] == "stop" for op in ctx.backend.ops)
        assert any(op[0] == "start" for op in ctx.backend.ops)
        kinds = [event.kind for event in ctx.bus.history]
        assert "device.unhealthy" in kinds

    import asyncio

    asyncio.run(scenario())
