import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from slash.agent.tree import UINode
from slash.agent.watchers import WatcherRule, load_rules, match_watcher
from slash.api.app import create_app
from slash.compat.harness import default_apps_path, load_apps, render_matrix
from slash.core.models import DeviceCreate
from slash.devices.backends.physical import PhysicalBackend
from slash.wiring import make_backend
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parents[2]
PIN = "cd6cea6ebde17af6685c2b325183fc24bef9d52b"


def _client(ctx):
    return TestClient(create_app(ctx, start_background=False))


def test_web_panel_is_served(world):
    client = _client(world())
    page = client.get("/")
    assert page.status_code == 200
    assert "交还" in page.text
    assert 'id="hand-back"' in page.text
    assert 'id="stream"' in page.text
    script = client.get("/assets/app.js")
    assert script.status_code == 200
    assert "/api/v1/takeover/" in script.text
    assert client.get("/assets/app.css").status_code == 200


def test_task_list_and_release_resumes(world):
    ctx = world(
        actions=[
            {"type": "ask_human", "reason": "需要扫码登录"},
            {"type": "done", "success": True, "result": "继续完成"},
        ]
    )
    client = _client(ctx)
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": device["id"], "goal": "登录", "mode": "tree"},
    ).json()
    assert task["status"] == "NEED_HUMAN"
    assert task["takeover_id"]
    listed = client.get("/api/v1/tasks", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task["id"]
    released = client.post(f"/api/v1/takeover/{task['takeover_id']}:release", headers=headers)
    assert released.status_code == 200, released.text
    assert released.json()["task_status"] == "SUCCEEDED"
    assert client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()["status"] == "SUCCEEDED"


def test_takeover_proxy_rejects_replay(world):
    ctx = world()
    client = _client(ctx)
    device = asyncio.run(ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id))
    issued = ctx.takeover.issue(device_id=device.id, task_id=None, reason="manual")
    token = issued.url.rstrip("/").split("/")[-1]
    first = client.get(f"/takeover/{token}/")
    assert first.status_code in {200, 502}
    replay = _client(ctx)
    replay.cookies.clear()
    again = replay.get(f"/takeover/{token}/")
    assert again.status_code == 401


def test_vision_only_skips_uiautomator_dump(world):
    ctx = world(
        mode="vision-only",
        vision=True,
        actions=[{"type": "done", "success": True, "result": "看到了"}],
    )
    client = _client(ctx)
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": device["id"], "goal": "看截图", "mode": "vision-only"},
    ).json()
    assert task["status"] == "SUCCEEDED", task
    assert not any("uiautomator" in str(call) for call in ctx.adb.calls)
    assert any("screencap" in str(call) for call in ctx.adb.calls)


def test_vision_only_requires_a_vision_provider(world):
    ctx = world(mode="vision-only", vision=False, actions=[{"type": "done", "success": True, "result": "x"}])
    client = _client(ctx)
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": device["id"], "goal": "看截图", "mode": "vision-only"},
    ).json()
    assert task["status"] == "FAILED"
    assert "vision" in task["error"]


def test_package_watcher_is_preferred():
    rules = load_rules()
    assert any(rule.package == "com.android.permissioncontroller" for rule in rules)
    nodes = [
        UINode(1, "android.widget.Button", "同意", "", "", "com.example.app", (0, 0, 10, 10), True, False, True),
        UINode(
            2,
            "android.widget.Button",
            "仅在使用中允许",
            "",
            "",
            "com.android.permissioncontroller",
            (0, 20, 10, 40),
            True,
            False,
            True,
        ),
    ]
    assert match_watcher(nodes, rules).text == "仅在使用中允许"
    custom_node = UINode(
        3, "android.widget.Button", "自定义继续", "", "", "com.example.app", (0, 0, 10, 10), True, False, True
    )
    custom = [WatcherRule(texts=("自定义继续",), package="com.example.app"), WatcherRule(texts=("同意",))]
    assert match_watcher([custom_node], custom).text == "自定义继续"


def test_compat_matrix_template_lists_sixteen_apps():
    apps = load_apps(default_apps_path())
    assert len(apps) >= 15
    assert any(item["mode"] == "vision-only" for item in apps)
    text = render_matrix(apps)
    assert text == (ROOT / "docs" / "compat-matrix.md").read_text(encoding="utf-8")
    assert "not run" in text
    assert "com.taobao.taobao" in text
    assert "com.tencent.mm" in text


def test_ws_scrcpy_pin_matches_dockerfile_and_compose():
    pin = (ROOT / "third_party" / "ws-scrcpy" / "PIN").read_text(encoding="utf-8")
    assert PIN in pin
    dockerfile = (ROOT / "third_party" / "ws-scrcpy" / "Dockerfile").read_text(encoding="utf-8")
    assert PIN in dockerfile
    assert "npm install" in dockerfile
    for name in ("docker-compose.yml", "docker-compose.multi.yml"):
        text = (ROOT / "deploy" / "compose" / name).read_text(encoding="utf-8")
        assert "ws-scrcpy:" in text
        assert PIN in text
        assert "127.0.0.1:8000:8000" in text
        assert "0.0.0.0:" not in text


def test_encrypted_backup_roundtrip(tmp_path):
    if shutil.which("openssl") is None or shutil.which("tar") is None:
        return
    data = tmp_path / "data"
    data.mkdir()
    (data / "session.txt").write_text("logged-in", encoding="utf-8")
    database = tmp_path / "slash.db"
    database.write_bytes(b"sqlite-bytes")
    archive = tmp_path / "out" / "device.tar.gz.enc"
    env = os.environ.copy()
    env["SLASH_BACKUP_PASSPHRASE"] = "test-passphrase"
    script = ROOT / "deploy" / "backup" / "backup.sh"
    backup = subprocess.run(
        ["bash", str(script), "backup", "--data", str(data), "--db", str(database), "--out", str(archive)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert backup.returncode == 0, backup.stderr
    assert archive.is_file()
    assert b"logged-in" not in archive.read_bytes()
    (data / "session.txt").write_text("gone", encoding="utf-8")
    restored = tmp_path / "restored"
    restored_db = tmp_path / "restored.db"
    restore = subprocess.run(
        [
            "bash",
            str(script),
            "restore",
            "--archive",
            str(archive),
            "--data",
            str(restored),
            "--db",
            str(restored_db),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert restore.returncode == 0, restore.stderr
    assert (restored / "session.txt").read_text(encoding="utf-8") == "logged-in"
    assert restored_db.read_bytes() == b"sqlite-bytes"


def test_physical_backend_keeps_the_configured_serial(tmp_path):
    config = make_config(tmp_path)
    config.devices.backend = "physical"
    config.devices.serials = {"handset": "emulator-5554"}
    backend = make_backend(config)
    assert isinstance(backend, PhysicalBackend)

    async def scenario():
        from slash.devices.fake_adb import FakeAdb
        from slash.wiring import build_context

        ctx = build_context(config, backend=backend, adb=FakeAdb(), inline_tasks=True)
        created = await ctx.manager.create(DeviceCreate(name="handset"), user_id=ctx.user_id)
        assert created.adb_serial == "emulator-5554"
        started = await ctx.manager.ensure_running(created.id)
        assert started.state == "RUNNING"
        assert await backend.adb_serial(created.id) == "emulator-5554"

    asyncio.run(scenario())


def test_k8s_network_policy_limits_adb():
    text = (ROOT / "deploy" / "k8s" / "base" / "networkpolicy.yaml").read_text(encoding="utf-8")
    assert "kind: NetworkPolicy" in text
    assert "port: 5555" in text
    assert "slash-phone" in text
    kustomize = (ROOT / "deploy" / "k8s" / "base" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "networkpolicy.yaml" in kustomize
    assert "statefulset-redroid.yaml" in kustomize
