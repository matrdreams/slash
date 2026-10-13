"""Task state machine that delegates execution to the Midscene worker.

PENDING -> PREPARING -> RUNNING, NEED_HUMAN as a pause, terminal SUCCEEDED / FAILED /
CANCELLED. Worker `step` events become StepRows + task events; `done` maps to the terminal
state; `need_human` issues a takeover link. Resume starts a fresh worker task with the
human's reply as context (Midscene has no in-place pause).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from slash.core.errors import ConflictError, SlashError
from slash.core.events import Event, EventBus
from slash.core.metrics import Metrics
from slash.core.models import TERMINAL_TASK_STATUSES, TaskStatus, assert_transition
from slash.devices.serial import serial_of
from slash.store.blobstore import BlobStore
from slash.store.db import Store
from slash.store.ids import new_id
from slash.store.tables import StepRow, TaskRow
from slash.store.timeutil import utcnow

_TERMINAL = {s.value for s in TERMINAL_TASK_STATUSES}


class MidsceneRuntime:
    def __init__(self, *, store: Store, blobs: BlobStore, manager, client, takeover,
                 bus: EventBus | None = None, metrics: Metrics | None = None) -> None:
        self.store = store
        self.blobs = blobs
        self.manager = manager
        self.client = client
        self.takeover = takeover
        self.bus = bus or EventBus()
        self.metrics = metrics or Metrics()
        self._locks: dict[str, asyncio.Lock] = {}
        self._worker_ids: dict[str, str] = {}
        self._takeover_requested: dict[str, str] = {}

    def _lock(self, device_id: str) -> asyncio.Lock:
        return self._locks.setdefault(device_id, asyncio.Lock())

    async def run(self, task_id: str, *, resume: bool = False) -> TaskRow:
        task = self.store.require_task(task_id)
        lock = self._lock(task.device_id)
        if lock.locked():
            raise ConflictError(f"device {task.device_id} is already running a task")
        async with lock:
            return await self._run_locked(task_id, resume=resume)

    async def _run_locked(self, task_id: str, *, resume: bool) -> TaskRow:
        task = self.store.require_task(task_id)
        other = self.store.active_task_for_device(task.device_id, ignore=task.id)
        if other is not None:
            raise ConflictError(f"device {task.device_id} is busy with task {other.id}")
        if not resume:
            self._set_status(task, TaskStatus.PREPARING)
            task = self.store.require_task(task.id)
            task.started_at = task.started_at or utcnow()
            self.store.save_task(task)
            try:
                await self.manager.ensure_running(task.device_id)
            except Exception as exc:
                self._fail(task, str(exc))
                return self.store.require_task(task.id)
        elif task.status != TaskStatus.NEED_HUMAN.value:
            raise ConflictError("only a NEED_HUMAN task can be resumed")
        self._set_status(self.store.require_task(task.id), TaskStatus.RUNNING)
        try:
            await self._drive(self.store.require_task(task.id))
        except Exception as exc:
            current = self.store.require_task(task.id)
            if current.status not in _TERMINAL and current.status != TaskStatus.NEED_HUMAN.value:
                self._fail(current, f"worker error: {exc}")
        return self.store.require_task(task.id)

    async def _drive(self, task: TaskRow) -> None:
        device = self.store.require_device(task.device_id)
        serial = serial_of(device)
        n = len([e for e in self.store.list_events(task.id) if e.event == "worker_submit"])
        worker_id = f"{task.id}-{n}"
        self._worker_ids[task.id] = worker_id
        context = ""
        if task.human_reply:
            context = (
                f"A human already intervened on the device. Their note: {task.human_reply}. "
                "Continue from the current screen."
            )
        remaining = max(1, (task.max_steps or 40) - (task.steps_used or 0))
        self._emit(task, "worker_submit", {"worker_task_id": worker_id})
        budget = None
        if task.max_cost_cny is not None:
            budget = max(0.0, task.max_cost_cny - (task.cost_cny or 0.0))
        await self.client.submit(task_id=worker_id, device_serial=serial, goal=task.goal,
                                 max_steps=remaining, context=context, max_cost_cny=budget)
        self._base_cost = task.cost_cny or 0.0
        self._last_usage: dict = {}
        started = time.monotonic()
        async for ev in self.client.follow(worker_id):
            kind = ev.get("type")
            data: dict[str, Any] = ev.get("data") or {}
            if kind == "step":
                self._record_step(task, data, started)
                started = time.monotonic()
            elif kind == "usage":
                self._record_usage(task, data)
            elif kind == "guard":
                self._emit(task, "guard", {"reason": data.get("reason")})
            elif kind == "done":
                if data.get("usage"):
                    self._record_usage(task, data["usage"])
                await self._finish(task, data)
                return
        current = self.store.require_task(task.id)
        if current.status not in _TERMINAL and current.status != TaskStatus.NEED_HUMAN.value:
            self._fail(current, "worker stream ended without a result")

    def _record_step(self, task: TaskRow, data: dict, started: float) -> None:
        task = self.store.require_task(task.id)
        idx = task.steps_used or 0
        phase = str(data.get("phase") or "")
        self.store.insert_step(StepRow(
            id=new_id(), task_id=task.id, idx=idx,
            action_json=json.dumps({"engine": "midscene", **data}, ensure_ascii=False, default=str),
            reasoning_summary=str(data.get("thought") or "")[:500],
            latency_ms=int((time.monotonic() - started) * 1000),
            error=phase if "failed" in phase else "",
        ))
        task.steps_used = idx + 1
        self.store.save_task(task)
        self.metrics.inc("slash_task_steps_total")
        self._emit(task, "step", {"idx": idx, "action": data.get("action"), "phase": phase})

    def _record_usage(self, task: TaskRow, usage: dict) -> None:
        """Worker usage is cumulative per worker task; store deltas on the latest step."""
        prev = self._last_usage or {}
        if usage.get("total_tokens") == prev.get("total_tokens"):
            return
        delta = {k: (usage.get(k) or 0) - (prev.get(k) or 0)
                 for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cost_cny")}
        self._last_usage = dict(usage)
        task = self.store.require_task(task.id)
        task.cost_cny = round(self._base_cost + float(usage.get("cost_cny") or 0.0), 5)
        self.store.save_task(task)
        steps = self.store.list_steps(task.id)
        if steps:
            last = steps[-1]
            old = json.loads(last.llm_usage_json or "{}")
            merged = {k: round((old.get(k) or 0) + v, 5) for k, v in delta.items()}
            last.llm_usage_json = json.dumps(merged)
            self.store.save_step(last)
        self.metrics.inc("slash_llm_tokens_total", delta["total_tokens"])
        self._emit(task, "usage", {**usage, "task_cost_cny": task.cost_cny})

    async def _finish(self, task: TaskRow, data: dict) -> None:
        task = self.store.require_task(task.id)
        if task.status in _TERMINAL:
            return
        state = data.get("state")
        report = data.get("report_path") or ""
        if report:
            self._emit(task, "report", {"path": report})
        requested = self._takeover_requested.pop(task.id, None)
        if requested is not None and state in ("cancelled", "failed"):
            await self._need_human(task, requested)
            return
        if state == "succeeded":
            self._succeed(task, str(data.get("result") or ""), report)
        elif state == "need_human":
            await self._need_human(task, str(data.get("reason") or "need human"))
        elif state == "cancelled":
            self._fail(task, "worker task cancelled")
        else:
            self._fail(task, str(data.get("error") or "worker failed"))

    async def _need_human(self, task: TaskRow, reason: str) -> None:
        task = self.store.require_task(task.id)
        device = self.store.require_device(task.device_id)
        issued = self.takeover.issue(device_id=task.device_id, task_id=task.id, reason=reason, serial=serial_of(device))
        task.takeover_url = issued.url
        self.store.save_task(task)
        self._set_status(task, TaskStatus.NEED_HUMAN)
        self._emit(task, "need_human", {"reason": reason, "url": issued.url, "expires_at": issued.expires_at.isoformat()})
        self.bus.publish(Event(kind="need_human", target=task.id, detail={"url": issued.url, "reason": reason}))

    def _succeed(self, task: TaskRow, result: str, report: str = "") -> None:
        task = self.store.require_task(task.id)
        task.result_json = json.dumps({"result": result, "report_path": report}, ensure_ascii=False)
        task.error = ""
        task.finished_at = utcnow()
        self.store.save_task(task)
        self._set_status(task, TaskStatus.SUCCEEDED)
        self._emit(task, "done", {"status": "SUCCEEDED", "result": result})
        self._ratio()

    def _fail(self, task: TaskRow, error: str) -> None:
        task = self.store.require_task(task.id)
        if task.status in _TERMINAL:
            return
        task.error = error
        task.finished_at = utcnow()
        self.store.save_task(task)
        try:
            self._set_status(task, TaskStatus.FAILED)
        except SlashError:
            task.status = TaskStatus.FAILED.value
            self.store.save_task(task)
        self._emit(task, "done", {"status": "FAILED", "error": error})
        self._ratio()

    def _set_status(self, task: TaskRow, status: TaskStatus) -> None:
        assert_transition(task.status, status)
        task.status = status.value
        if status in TERMINAL_TASK_STATUSES:
            task.finished_at = task.finished_at or utcnow()
        self.store.save_task(task)
        self._emit(task, "status", {"status": status.value})

    def _emit(self, task: TaskRow, event: str, data: dict) -> None:
        self.store.add_event(task.id, event, data)

    def _ratio(self) -> None:
        done = ok = 0
        for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            rows = self.store.tasks_by_status(status)
            done += len(rows)
            if status is TaskStatus.SUCCEEDED:
                ok += len(rows)
        if done:
            self.metrics.set_gauge("slash_task_success_ratio", ok / done)

    async def _release_takeovers(self, task_id: str) -> None:
        if self.takeover is None:
            return
        for row in list(self.store.list_open_takeovers()):
            if row.task_id == task_id:
                await self.takeover.release(row.id)

    async def cancel(self, task_id: str) -> TaskRow:
        task = self.store.require_task(task_id)
        assert_transition(task.status, TaskStatus.CANCELLED)
        worker_id = self._worker_ids.get(task_id)
        if worker_id:
            try:
                await self.client.cancel(worker_id)
            except Exception:
                pass
        await self._release_takeovers(task_id)
        task = self.store.require_task(task_id)
        self._set_status(task, TaskStatus.CANCELLED)
        task = self.store.require_task(task_id)
        task.finished_at = utcnow()
        self.store.save_task(task)
        self._emit(task, "done", {"status": "CANCELLED"})
        return task

    async def request_takeover(self, task_id: str, reason: str = "user requested takeover") -> TaskRow:
        """User-initiated takeover of a RUNNING task: cancel the worker task; the runner then
        moves the task to NEED_HUMAN and issues a takeover link."""
        task = self.store.require_task(task_id)
        if task.status != TaskStatus.RUNNING.value:
            raise ConflictError("only a RUNNING task can be taken over")
        self._takeover_requested[task_id] = reason
        worker_id = self._worker_ids.get(task_id)
        if worker_id:
            await self.client.cancel(worker_id)
        return self.store.require_task(task_id)

    async def resume(self, task_id: str, *, text: str = "") -> TaskRow:
        task = self.store.require_task(task_id)
        if task.status != TaskStatus.NEED_HUMAN.value:
            raise ConflictError("only a NEED_HUMAN task can be resumed")
        if text:
            task.human_reply = text
            self.store.save_task(task)
        return await self.run(task_id, resume=True)

    async def reply(self, task_id: str, text: str) -> TaskRow:
        task = self.store.require_task(task_id)
        if task.status != TaskStatus.NEED_HUMAN.value:
            raise ConflictError("task is not waiting for a person")
        task.human_reply = text
        self.store.save_task(task)
        await self._release_takeovers(task_id)
        return await self.resume(task_id)
