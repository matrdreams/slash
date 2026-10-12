"""Step loop and the task state machine.

PENDING -> PREPARING -> RUNNING, with NEED_HUMAN as a pause and terminal
SUCCEEDED / FAILED / CANCELLED states. Each step stores the screenshot, the
compressed tree, and the action.
"""

import json
import time
from typing import Any

from slash.agent.actions import ACTION_ADAPTER, AskHuman, Done
from slash.agent.actuator import Actuator
from slash.agent.detectors import need_human
from slash.agent.observer import Observer
from slash.agent.policy import as_confirmation, sensitive_reason
from slash.agent.redact import should_redact
from slash.agent.watchers import WatcherRule, match_watcher
from slash.core.errors import BudgetExceeded, ConflictError, SlashError
from slash.core.events import Event, EventBus
from slash.core.metrics import Metrics
from slash.core.models import TERMINAL_TASK_STATUSES, TaskStatus, assert_transition
from slash.devices.serial import serial_of
from slash.store.blobstore import BlobStore
from slash.store.db import Store
from slash.store.ids import new_id
from slash.store.tables import StepRow, TaskRow
from slash.store.timeutil import utcnow


class AgentRuntime:
    def __init__(
        self,
        *,
        store: Store,
        blobs: BlobStore,
        manager,
        observer: Observer,
        actuator: Actuator,
        planner,
        takeover,
        bus: EventBus | None = None,
        metrics: Metrics | None = None,
        watchers: list[WatcherRule] | None = None,
    ) -> None:
        self.store = store
        self.blobs = blobs
        self.manager = manager
        self.observer = observer
        self.actuator = actuator
        self.planner = planner
        self.takeover = takeover
        self.bus = bus or EventBus()
        self.metrics = metrics or Metrics()
        self.watchers = watchers
        self._locks: dict[str, Any] = {}

    def _lock(self, device_id: str):
        import asyncio

        lock = self._locks.get(device_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[device_id] = lock
        return lock

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
            self._set_status(task, TaskStatus.RUNNING)
        else:
            if task.status != TaskStatus.NEED_HUMAN.value:
                raise ConflictError("only a NEED_HUMAN task can be resumed")
            self._set_status(task, TaskStatus.RUNNING)

        device = self.store.require_device(task.device_id)
        serial = serial_of(device)
        if hasattr(self.planner, "mode"):
            self.planner.mode = task.mode
        if task.mode == "vision-only" and not getattr(self.planner.provider, "supports_vision", False):
            self._fail(task, "provider does not support vision")
            return self.store.require_task(task.id)
        try:
            await self._steps(task, device, serial)
        except BudgetExceeded as exc:
            self._fail(self.store.require_task(task.id), str(exc))
        except Exception as exc:
            current = self.store.require_task(task.id)
            if current.status not in {status.value for status in TERMINAL_TASK_STATUSES}:
                if current.status != TaskStatus.NEED_HUMAN.value:
                    self._fail(current, str(exc))
        return self.store.require_task(task.id)

    async def _steps(self, task: TaskRow, device, serial: str) -> None:
        while True:
            task = self.store.require_task(task.id)
            if task.status == TaskStatus.CANCELLED.value:
                self._emit(task, "done", {"status": task.status})
                return
            if task.steps_used >= task.max_steps:
                self._fail(task, "max_steps exceeded")
                return
            started = time.monotonic()
            obs = await self.observer.observe(serial, mode=task.mode)
            provider_region = getattr(self.planner.provider, "region", "local")
            redact = should_redact(tree_text=obs.tree_text, provider_region=provider_region)
            self.observer.apply_redaction(obs, enabled=redact)

            watcher = match_watcher(obs.nodes, self.watchers, package=obs.package)
            if watcher is not None:
                from slash.agent.actions import Tap

                action = Tap(element_id=watcher.element_id)
                await self.actuator.execute(serial, action, obs.nodes, width=device.width, height=device.height)
                self._record(task, obs, action, None, started, error="")
                self.manager.touch(task.device_id)
                continue

            reason = need_human(obs.tree_text)
            if reason:
                self._record(task, obs, AskHuman(reason=f"检测到{reason}"), None, started, error="")
                await self._need_human(task, f"检测到{reason}")
                return

            action, result = await self.planner.next(
                task.goal,
                self._history(task.id),
                obs,
                device,
                human_reply=task.human_reply,
            )
            self._charge(task, result)
            if task.require_confirm:
                blocked = sensitive_reason(action, obs.nodes)
                if blocked:
                    action = as_confirmation(blocked)
            if isinstance(action, AskHuman):
                self._record(task, obs, action, result, started, error="")
                await self._need_human(task, action.reason)
                return
            if isinstance(action, Done):
                self._record(task, obs, action, result, started, error="")
                if action.success:
                    self._succeed(task, action.result)
                else:
                    self._fail(task, action.result or "done success=false")
                return
            try:
                await self.actuator.execute(serial, action, obs.nodes, width=device.width, height=device.height)
            except Exception as exc:
                self._record(task, obs, action, result, started, error=str(exc))
                self._fail(task, str(exc))
                return
            self._record(task, obs, action, result, started, error="")
            self.manager.touch(task.device_id)

    def _charge(self, task: TaskRow, result) -> None:
        if result is None:
            return
        task.tokens_in += result.usage.prompt_tokens
        task.tokens_out += result.usage.completion_tokens
        task.cost_cny += float(result.cost_cny)
        used = result.usage.prompt_tokens + result.usage.completion_tokens
        provider_name = getattr(self.planner.provider, "name", "unknown")
        self.metrics.inc("slash_llm_tokens_total", used, provider=provider_name)
        self.metrics.inc("slash_llm_cost_cny_total", float(result.cost_cny), provider=provider_name)
        self.store.save_task(task)
        limit = task.max_cost_cny
        if limit is not None and task.cost_cny > limit:
            raise BudgetExceeded(f"cost {task.cost_cny:.4f} exceeds max_cost_cny {limit}")

    def _record(self, task: TaskRow, obs, action, result, started: float, *, error: str) -> None:
        task = self.store.require_task(task.id)
        idx = task.steps_used
        tree_ref = self.blobs.put(task.id, f"step-{idx}-tree.txt", data=obs.tree_text.encode("utf-8"))
        shot_ref = ""
        if obs.screenshot:
            shot_ref = self.blobs.put(task.id, f"step-{idx}.png", data=obs.screenshot)
        payload = ACTION_ADAPTER.dump_python(action, mode="json")
        usage = {}
        summary = ""
        if result is not None:
            usage = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "images": result.usage.images,
                "cost_cny": result.cost_cny,
                "redacted": obs.redacted,
            }
            summary = (result.text or "")[:500]
        elif isinstance(action, AskHuman):
            summary = action.reason
        row = StepRow(
            id=new_id(),
            task_id=task.id,
            idx=idx,
            observation_ref=tree_ref,
            screenshot_ref=shot_ref,
            action_json=json.dumps(payload, ensure_ascii=False),
            reasoning_summary=summary,
            latency_ms=int((time.monotonic() - started) * 1000),
            llm_usage_json=json.dumps(usage),
            error=error,
        )
        self.store.insert_step(row)
        task.steps_used = idx + 1
        self.store.save_task(task)
        self.metrics.inc("slash_task_steps_total")
        self._emit(task, "step", {"idx": idx, "action": payload, "error": error})

    async def _need_human(self, task: TaskRow, reason: str) -> None:
        task = self.store.require_task(task.id)
        device = self.store.require_device(task.device_id)
        issued = self.takeover.issue(
            device_id=task.device_id,
            task_id=task.id,
            reason=reason,
            serial=serial_of(device),
        )
        task.takeover_url = issued.url
        self.store.save_task(task)
        self._set_status(task, TaskStatus.NEED_HUMAN)
        self._emit(
            task,
            "need_human",
            {"reason": reason, "url": issued.url, "expires_at": issued.expires_at.isoformat()},
        )
        self.bus.publish(Event(kind="need_human", target=task.id, detail={"url": issued.url, "reason": reason}))

    def _succeed(self, task: TaskRow, result: str) -> None:
        task = self.store.require_task(task.id)
        task.result_json = json.dumps({"result": result}, ensure_ascii=False)
        task.error = ""
        task.finished_at = utcnow()
        self.store.save_task(task)
        self._set_status(task, TaskStatus.SUCCEEDED)
        self._emit(task, "done", {"status": "SUCCEEDED", "result": result})
        self._ratio()

    def _fail(self, task: TaskRow, error: str) -> None:
        task = self.store.require_task(task.id)
        if task.status in {status.value for status in TERMINAL_TASK_STATUSES}:
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

    def _history(self, task_id: str) -> list[dict]:
        rows = []
        for step in self.store.list_steps(task_id):
            rows.append(
                {
                    "idx": step.idx,
                    "action": json.loads(step.action_json or "{}"),
                    "error": step.error,
                }
            )
        return rows

    def _ratio(self) -> None:
        done = 0
        ok = 0
        for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            rows = self.store.tasks_by_status(status)
            done += len(rows)
            if status is TaskStatus.SUCCEEDED:
                ok += len(rows)
        if done:
            self.metrics.set_gauge("slash_task_success_ratio", ok / done)

    async def cancel(self, task_id: str) -> TaskRow:
        task = self.store.require_task(task_id)
        assert_transition(task.status, TaskStatus.CANCELLED)
        if self.takeover is not None:
            for row in list(self.store.list_open_takeovers()):
                if row.task_id == task_id:
                    await self.takeover.release(row.id)
        task = self.store.require_task(task_id)
        self._set_status(task, TaskStatus.CANCELLED)
        task = self.store.require_task(task_id)
        task.finished_at = utcnow()
        self.store.save_task(task)
        self._emit(task, "done", {"status": "CANCELLED"})
        return task

    async def resume(self, task_id: str, *, text: str = "") -> TaskRow:
        """Continue a NEED_HUMAN task after the person hands control back."""
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
        if self.takeover is not None:
            for row in list(self.store.list_open_takeovers()):
                if row.task_id == task_id:
                    await self.takeover.release(row.id)
        return await self.resume(task_id)
