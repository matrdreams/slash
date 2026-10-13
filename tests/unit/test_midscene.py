"""Midscene worker client + runtime, all offline (mocked worker over httpx MockTransport)."""

import asyncio
import json

import httpx

from slash.agent.midscene_client import MidsceneClient
from slash.devices.u2 import U2Device, check_search_text, find_in_hierarchy

XML = (
    '<hierarchy><node resource-id="com.android.settings:id/search_src_text" text="Display" />'
    '<node resource-id="android:id/title" text="显示" /></hierarchy>'
)


def test_find_in_hierarchy_and_checker():
    assert find_in_hierarchy(XML, resource_id="search_src_text") == ["Display"]
    assert find_in_hierarchy(XML, text="显示") == ["显示"]

    class D:
        def dump_hierarchy(self, compressed=False):
            return XML

        def send_keys(self, text, clear=False):
            self.sent = text

    dev = U2Device.connect("x", factory=lambda serial: D())
    assert check_search_text(dev, "Display")
    assert not check_search_text(dev, "Battery")
    dev.send_keys("显示")
    assert dev.raw.sent == "显示"


def _transport():
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tasks" and request.method == "POST":
            body = json.loads(request.content)
            assert body["device_serial"] == "127.0.0.1:15555"
            return httpx.Response(200, json={"id": body["task_id"], "state": "queued"})
        if request.url.path.endswith("/events"):
            state["polls"] += 1
            if state["polls"] == 1:
                return httpx.Response(200, json={"state": "running", "events": [
                    {"seq": 0, "type": "status", "data": {"state": "running"}},
                    {"seq": 1, "type": "step", "data": {"idx": 0, "phase": "action_done"}}]})
            assert request.url.params["after"] == "1"
            return httpx.Response(200, json={"state": "succeeded", "events": [
                {"seq": 2, "type": "done", "data": {"state": "succeeded", "result": "ok", "report_path": "/r.html"}}]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_client_follows_events_until_done():
    async def scenario():
        client = MidsceneClient("http://worker", poll_s=0, transport=_transport())
        assert (await client.health())["ok"]
        await client.submit(task_id="t-0", device_serial="127.0.0.1:15555", goal="g")
        events = [ev async for ev in client.follow("t-0")]
        await client.aclose()
        return events

    events = asyncio.run(scenario())
    assert [e["type"] for e in events] == ["status", "step", "done"]


def test_task_through_api_maps_worker_events(world):
    from fastapi.testclient import TestClient

    from slash.api.app import create_app

    ctx = world(actions=[{"type": "done", "success": True, "result": "done"}])
    client = TestClient(create_app(ctx, start_background=False))
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post("/api/v1/tasks", headers=headers, json={"device_id": device["id"], "goal": "open Settings"}).json()
    assert task["status"] == "SUCCEEDED", task
    steps = client.get(f"/api/v1/tasks/{task['id']}/steps", headers=headers).json()
    assert len(steps) == 1
    events = [e.event for e in ctx.store.list_events(task["id"])]
    assert "worker_submit" in events and "report" in events
    assert ctx.worker.submitted[0]["goal"] == "open Settings"


def test_need_human_then_reply_resumes_with_context(world):
    from fastapi.testclient import TestClient

    from slash.api.app import create_app

    ctx = world(actions=[{"type": "ask_human", "reason": "扫码"}, {"type": "done", "success": True, "result": "ok"}])
    client = TestClient(create_app(ctx, start_background=False))
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post("/api/v1/tasks", headers=headers, json={"device_id": device["id"], "goal": "登录"}).json()
    assert task["status"] == "NEED_HUMAN" and task["takeover_url"]
    done = client.post(f"/api/v1/tasks/{task['id']}:reply", headers=headers, json={"text": "扫好了"}).json()
    assert done["status"] == "SUCCEEDED"
    assert "扫好了" in ctx.worker.submitted[1]["context"]
    assert ctx.worker.submitted[1]["task_id"].endswith("-1")


def test_user_takeover_of_running_task(world):
    from slash.core.models import TaskStatus

    ctx = world(actions=[])
    rt = ctx.runtime

    class SlowClient:
        def __init__(self):
            self.cancel_event = asyncio.Event()
            self.cancelled = []

        async def submit(self, **kw):
            return {}

        async def cancel(self, task_id):
            self.cancelled.append(task_id)
            self.cancel_event.set()
            return {}

        async def follow(self, task_id):
            yield {"type": "step", "data": {"idx": 0, "phase": "action_done"}}
            await self.cancel_event.wait()
            yield {"type": "done", "data": {"state": "cancelled"}}

    rt.client = SlowClient()

    async def scenario():
        from slash.core.models import DeviceCreate
        from slash.store.ids import new_id
        from slash.store.tables import TaskRow

        device = await ctx.manager.create(DeviceCreate(name="u1"), user_id=ctx.user_id)
        task = ctx.store.insert_task(TaskRow(id=new_id(), device_id=device.id, goal="g",
                                             status=TaskStatus.PENDING.value, provider="fake", mode="tree"))
        runner = asyncio.create_task(rt.run(task.id))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if ctx.store.require_task(task.id).status == TaskStatus.RUNNING.value and ctx.store.list_steps(task.id):
                break
        await rt.request_takeover(task.id)
        return await runner

    final = asyncio.run(scenario())
    assert final.status == TaskStatus.NEED_HUMAN.value
    assert final.takeover_url


def test_usage_fills_cost_and_step_usage(world):
    from fastapi.testclient import TestClient

    from slash.api.app import create_app

    usage = {"calls": 3, "prompt_tokens": 30000, "completion_tokens": 300, "total_tokens": 30300, "cost_cny": 0.0945}
    ctx = world(actions=[{"type": "done", "success": True, "result": "ok", "usage": usage}], max_cost_cny=1.0)
    client = TestClient(create_app(ctx, start_background=False))
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post("/api/v1/tasks", headers=headers, json={"device_id": device["id"], "goal": "g"}).json()
    assert task["status"] == "SUCCEEDED"
    assert abs(task["cost_cny"] - 0.0945) < 1e-9
    assert ctx.worker.submitted[0]["max_cost_cny"] == 1.0
    step = ctx.store.list_steps(task["id"])[-1]
    assert json.loads(step.llm_usage_json)["total_tokens"] == 30300


def test_budget_failure_from_worker_maps_to_failed(world):
    from fastapi.testclient import TestClient

    from slash.api.app import create_app

    ctx = world(actions=[{"state": "failed", "error": "budget exceeded: ¥0.6 > max_cost_cny ¥0.5"}])
    client = TestClient(create_app(ctx, start_background=False))
    headers = {"Authorization": "Bearer test-token"}
    device = client.post("/api/v1/devices", headers=headers, json={"name": "u1"}).json()
    task = client.post("/api/v1/tasks", headers=headers, json={"device_id": device["id"], "goal": "g"}).json()
    assert task["status"] == "FAILED" and "budget" in task["error"]
