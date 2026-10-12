"""Task routes, including the SSE event stream."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from slash.api.deps import require_bearer
from slash.api.serialize import step_out, task_out
from slash.api.ws import format_sse
from slash.core.models import TERMINAL_TASK_STATUSES, ReplyIn, TaskCreate, TaskStatus
from slash.store.ids import new_id
from slash.store.tables import TaskRow

router = APIRouter(prefix="/tasks", dependencies=[Depends(require_bearer)])


def _state(request: Request):
    return request.app.state.ctx


@router.post("")
async def create_task(body: TaskCreate, request: Request):
    state = _state(request)
    device = state.store.get_device(body.device_id) or state.store.get_device_by_name(body.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if body.session_id:
        session = state.store.get_session(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if session.device_id != device.id:
            raise HTTPException(status_code=409, detail="session is bound to another device")
    busy = state.store.active_task_for_device(device.id)
    if busy is not None:
        raise HTTPException(status_code=409, detail=f"device is busy with task {busy.id}")
    mode = body.mode or state.config.agent.mode
    provider = body.provider or state.config.llm.default
    limit = body.max_cost_cny if body.max_cost_cny is not None else state.config.llm.max_cost_cny
    row = TaskRow(
        id=new_id(),
        session_id=body.session_id,
        device_id=device.id,
        goal=body.goal,
        app=body.app,
        mode=mode,
        provider=provider,
        status=TaskStatus.PENDING.value,
        max_steps=body.max_steps or state.config.agent.max_steps,
        max_cost_cny=limit,
        require_confirm=state.config.agent.confirm_sensitive if body.require_confirm is None else body.require_confirm,
    )
    saved = state.store.insert_task(row)
    state.store.audit("task.create", saved.id, {"goal": body.goal, "device_id": device.id})
    if state.inline_tasks:
        await state.runtime.run(saved.id)
    else:
        asyncio.create_task(state.runtime.run(saved.id))
    return task_out(state.store.require_task(saved.id))


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request):
    return task_out(_state(request).store.require_task(task_id))


@router.get("/{task_id}/steps")
async def list_steps(task_id: str, request: Request):
    state = _state(request)
    state.store.require_task(task_id)
    return [step_out(row) for row in state.store.list_steps(task_id)]


@router.get("/{task_id}/steps/{idx}/screenshot")
async def step_screenshot(task_id: str, idx: int, request: Request):
    state = _state(request)
    for row in state.store.list_steps(task_id):
        if row.idx == idx and row.screenshot_ref:
            return Response(content=state.blobs.get(row.screenshot_ref), media_type="image/png")
    raise HTTPException(status_code=404, detail="screenshot not found")


@router.get("/{task_id}/events")
async def task_events(task_id: str, request: Request):
    state = _state(request)
    state.store.require_task(task_id)

    async def generate():
        sent = 0
        idle_rounds = 0
        while idle_rounds < 3:
            rows = state.store.list_events(task_id)
            for row in rows[sent:]:
                yield format_sse(row.event, row.data_json)
                sent += 1
                idle_rounds = 0
            task = state.store.get_task(task_id)
            terminal = task is not None and task.status in {item.value for item in TERMINAL_TASK_STATUSES}
            if terminal and sent >= len(state.store.list_events(task_id)):
                if sent == 0:
                    yield format_sse("status", json.dumps({"status": task.status}))
                break
            if task is not None and task.status == TaskStatus.NEED_HUMAN.value and sent >= len(rows):
                break
            idle_rounds += 1
            await asyncio.sleep(0.01)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{task_id}:cancel")
async def cancel_task(task_id: str, request: Request):
    return task_out(await _state(request).runtime.cancel(task_id))


@router.post("/{task_id}/cancel")
async def cancel_task_slash(task_id: str, request: Request):
    return task_out(await _state(request).runtime.cancel(task_id))


@router.post("/{task_id}:reply")
async def reply_task(task_id: str, body: ReplyIn, request: Request):
    return task_out(await _state(request).runtime.reply(task_id, body.text))


@router.post("/{task_id}/reply")
async def reply_task_slash(task_id: str, body: ReplyIn, request: Request):
    return task_out(await _state(request).runtime.reply(task_id, body.text))
