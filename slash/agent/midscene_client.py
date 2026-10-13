"""httpx client for the Node Midscene worker (see worker/src/server.ts)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx


class MidsceneClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0, poll_s: float = 1.0, transport=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.poll_s = poll_s
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport)

    async def health(self) -> dict:
        r = await self._client.get("/health")
        r.raise_for_status()
        return r.json()

    async def submit(self, *, task_id: str, device_serial: str, goal: str, max_steps: int | None = None,
                     context: str = "", max_cost_cny: float | None = None) -> dict:
        body: dict[str, Any] = {"task_id": task_id, "device_serial": device_serial, "goal": goal}
        if max_steps:
            body["max_steps"] = max_steps
        if context:
            body["context"] = context
        if max_cost_cny is not None:
            body["max_cost_cny"] = max_cost_cny
        r = await self._client.post("/tasks", json=body)
        r.raise_for_status()
        return r.json()

    async def cancel(self, task_id: str) -> dict:
        r = await self._client.post(f"/tasks/{task_id}/cancel")
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def events(self, task_id: str, after: int = -1) -> dict:
        r = await self._client.get(f"/tasks/{task_id}/events", params={"after": after})
        r.raise_for_status()
        return r.json()

    async def follow(self, task_id: str) -> AsyncIterator[dict]:
        """Poll events until a `done` event; yields each event dict."""
        after = -1
        while True:
            page = await self.events(task_id, after)
            for ev in page.get("events", []):
                after = max(after, int(ev.get("seq", after)))
                yield ev
                if ev.get("type") == "done":
                    return
            await asyncio.sleep(self.poll_s)

    async def aclose(self) -> None:
        await self._client.aclose()


class FakeMidsceneClient:
    """In-process stand-in used by tests and the `fake` device backend.

    `script` is consumed one item per submit: legacy scripted-provider shapes
    ({"type": "done", ...} / {"type": "ask_human", "reason": ...}) or worker states
    ({"state": "failed", "error": ...}).
    """

    def __init__(self, script: list[dict] | None = None) -> None:
        self.script = list(script or [])
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        self._out: dict[str, list[dict]] = {}

    async def health(self) -> dict:
        return {"ok": True, "mock": True}

    async def submit(self, *, task_id: str, device_serial: str, goal: str, max_steps=None, context: str = "",
                     max_cost_cny: float | None = None) -> dict:
        self.submitted.append({"max_cost_cny": max_cost_cny, "task_id": task_id, "device_serial": device_serial, "goal": goal, "context": context})
        events: list[dict] = [{"seq": 0, "type": "status", "data": {"state": "running"}}]
        terminal = {"done", "succeeded", "ask_human", "need_human", "confirm", "failed"}
        item: dict = {}
        while True:
            item = self.script.pop(0) if self.script else {"state": "failed", "error": "fake worker script exhausted"}
            kind = item.get("type") or item.get("state")
            events.append({"seq": len(events), "type": "step",
                           "data": {"idx": len(events) - 1, "phase": "action_done", "action": dict(item)}})
            if kind in terminal:
                break
        kind = item.get("type") or item.get("state")
        if kind in ("done", "succeeded"):
            ok = item.get("success", True)
            data = {
                "state": "succeeded" if ok else "failed",
                "result": item.get("result", ""),
                "error": "" if ok else item.get("result", "failed"),
                "report_path": "/tmp/fake-report.html",
            }
        elif kind in ("ask_human", "need_human", "confirm"):
            data = {"state": "need_human", "reason": item.get("reason", "need human")}
        else:
            data = {"state": "failed", "error": item.get("error", "failed")}
        if item.get("usage"):
            data["usage"] = item["usage"]
        events.append({"seq": len(events), "type": "done", "data": data})
        self._out[task_id] = events
        return {"id": task_id, "state": "queued"}

    async def cancel(self, task_id: str) -> dict:
        self.cancelled.append(task_id)
        return {}

    async def follow(self, task_id: str):
        for ev in self._out.pop(task_id, []):
            yield ev

    async def aclose(self) -> None:
        return None
