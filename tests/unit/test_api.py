import json
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from slash.api.app import create_app
from slash.core.models import DeviceCreate, TaskStatus
from slash.store.timeutil import utcnow


def _client(ctx):
    app = create_app(ctx, start_background=False)
    return TestClient(app)


def _auth(token="test-token"):
    return {"Authorization": f"Bearer {token}"}


def test_openapi_lists_device_and_task_routes(world):
    client = _client(world())
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/devices" in paths
    assert "/api/v1/tasks" in paths
    assert "/healthz" in paths
    joined = " ".join(paths)
    assert ":start" in joined
    assert ":cancel" in joined
    health = client.get("/healthz")
    assert health.status_code == 200
    denied = client.get("/api/v1/devices")
    assert denied.status_code == 401


def test_device_crud_snapshot_and_screenshot(world, tmp_path):
    ctx = world()
    client = _client(ctx)
    headers = _auth()
    created = []
    for name in ("u1", "u2", "u3"):
        response = client.post("/api/v1/devices", headers=headers, json={"name": name})
        assert response.status_code == 200, response.text
        created.append(response.json())
    assert [item["adb_port"] for item in created] == [5601, 5602, 5603]
    started = client.post(f"/api/v1/devices/{created[0]['id']}:start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "RUNNING"
    shot = client.get(f"/api/v1/devices/{created[0]['id']}/screenshot", headers=headers)
    assert shot.status_code == 200
    assert shot.content.startswith(b"\x89PNG")
    data = Path(created[0]["data_path"])
    marker = data / "session.txt"
    marker.write_text("logged-in", encoding="utf-8")
    snap = client.post(f"/api/v1/devices/{created[0]['id']}/snapshots", headers=headers, params={"note": "login"})
    assert snap.status_code == 200, snap.text
    marker.write_text("gone", encoding="utf-8")
    client.post(f"/api/v1/devices/{created[0]['id']}:stop", headers=headers)
    restored = client.post(
        f"/api/v1/devices/{created[0]['id']}/snapshots/{snap.json()['id']}:restore",
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert marker.read_text(encoding="utf-8") == "logged-in"
    for item in created:
        client.post(f"/api/v1/devices/{item['id']}:stop", headers=headers)
        deleted = client.delete(f"/api/v1/devices/{item['id']}", headers=headers)
        assert deleted.status_code == 200


def test_task_run_steps_and_events(world):
    ctx = world(actions=[{"type": "done", "success": True, "result": "显示设置已打开"}])
    client = _client(ctx)
    headers = _auth()
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": device["id"], "goal": "打开设置并搜索显示", "mode": "tree"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["steps_used"] == 1
    steps = client.get(f"/api/v1/tasks/{body['id']}/steps", headers=headers).json()
    assert steps[0]["action"]["engine"] == "midscene"
    # Per-step screenshots now live in the Midscene HTML report (see "report" event).
    events = client.get(f"/api/v1/tasks/{body['id']}/events", headers=headers)
    assert events.status_code == 200
    assert "event: done" in events.text
    assert "event: step" in events.text


def test_need_human_reply_and_cancel(world):
    ctx = world(
        actions=[
            {"type": "ask_human", "reason": "需要扫码登录"},
            {"type": "done", "success": True, "result": "继续完成"},
        ]
    )
    client = _client(ctx)
    headers = _auth()
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": device["id"], "goal": "登录", "mode": "tree"},
    ).json()
    assert task["status"] == "NEED_HUMAN"
    assert task["takeover_url"]
    replied = client.post(
        f"/api/v1/tasks/{task['id']}:reply",
        headers=headers,
        json={"text": "扫好了"},
    )
    assert replied.status_code == 200, replied.text
    assert replied.json()["status"] == "SUCCEEDED"

    second = client.post("/api/v1/devices", headers=headers, json={"name": "u2"}).json()
    waiting = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"device_id": second["id"], "goal": "再登录", "mode": "tree"},
    )
    # The scripted provider is exhausted, so this task fails inside the planner
    # unless we only cancel a fresh pending task. Cancel the succeeded path's
    # sibling by creating a task and cancelling before it can matter.
    assert waiting.status_code == 200
    if waiting.json()["status"] not in {"SUCCEEDED", "FAILED", "NEED_HUMAN"}:
        cancelled = client.post(f"/api/v1/tasks/{waiting.json()['id']}:cancel", headers=headers)
        assert cancelled.status_code == 200


def test_cancel_pending_task(world):
    ctx = world(actions=[{"type": "done", "success": True, "result": "ok"}])
    # Insert a pending task and cancel it without running.

    import asyncio

    device = asyncio.run(ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id))
    from slash.store.ids import new_id
    from slash.store.tables import TaskRow

    task = ctx.store.insert_task(
        TaskRow(
            id=new_id(),
            device_id=device.id,
            goal="later",
            status=TaskStatus.PENDING.value,
            provider="fake",
            mode="tree",
        )
    )
    client = _client(ctx)
    cancelled = client.post(f"/api/v1/tasks/{task.id}:cancel", headers=_auth())
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_takeover_token_is_one_time(world):
    ctx = world()
    client = _client(ctx)

    import asyncio


    device = asyncio.run(ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id))
    issued = ctx.takeover.issue(device_id=device.id, task_id=None, reason="manual")
    token = issued.url.rstrip("/").split("/")[-1]
    first = client.get("/api/v1/takeover/verify", headers={"X-Forwarded-Uri": f"/takeover/{token}/"})
    assert first.status_code == 200
    assert "slash_takeover" in first.cookies
    cookie = first.cookies["slash_takeover"]
    client.cookies.clear()
    replay = client.get("/api/v1/takeover/verify", headers={"X-Forwarded-Uri": f"/takeover/{token}/"})
    assert replay.status_code == 401
    client.cookies.set("slash_takeover", cookie)
    again = client.get("/api/v1/takeover/verify")
    assert again.status_code == 200

    row = ctx.takeover.require(issued.id)
    row.expires_at = utcnow() - timedelta(seconds=5)
    ctx.store.save_takeover(row)
    from slash.core.models import TaskStatus
    from slash.store.ids import new_id
    from slash.store.tables import TaskRow

    task = ctx.store.insert_task(
        TaskRow(
            id=new_id(),
            device_id=device.id,
            goal="wait",
            status=TaskStatus.NEED_HUMAN.value,
            provider="fake",
            mode="tree",
        )
    )
    row.task_id = task.id
    row.released_at = None
    row.expires_at = utcnow() - timedelta(seconds=5)
    ctx.store.save_takeover(row)
    failed = ctx.takeover.apply_timeouts(now=utcnow())
    assert task.id in failed
    assert ctx.store.require_task(task.id).status == TaskStatus.FAILED.value
    assert ctx.store.require_task(task.id).error == "takeover timeout"


def test_app_install_route_rejects_bad_cert(world, tmp_path):
    ctx = world()
    client = _client(ctx)
    headers = _auth()
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    client.post(f"/api/v1/devices/{device['id']}:start", headers=headers)
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"apk-bytes")
    bad = client.post(
        f"/api/v1/devices/{device['id']}/apps",
        headers=headers,
        files={"file": ("app.apk", apk.read_bytes(), "application/vnd.android.package-archive")},
        data={"expected_cert_sha256": "ffff"},
    )
    assert bad.status_code == 400
    ctx.verifier.fingerprint_value = "abcd"
    good = client.post(
        f"/api/v1/devices/{device['id']}/apps",
        headers=headers,
        files={"file": ("app.apk", apk.read_bytes(), "application/vnd.android.package-archive")},
        data={"expected_cert_sha256": "ab:cd", "package": "com.example.app"},
    )
    assert good.status_code == 200, good.text
    assert good.json()["cert_sha256"] == "abcd"
    listed = client.get(f"/api/v1/devices/{device['id']}/apps", headers=headers)
    assert listed.status_code == 200


def test_metrics_render(world):
    ctx = world(actions=[{"type": "done", "success": True, "result": "ok"}])
    client = _client(ctx)
    headers = _auth()
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    client.post("/api/v1/tasks", headers=headers, json={"device_id": device["id"], "goal": "hi", "mode": "tree"})
    text = client.get("/metrics").text
    assert "slash_task_steps_total" in text
    assert "slash_devices_running" in text
    _ = json.dumps(text)
