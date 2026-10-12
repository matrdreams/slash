"""Row to response-model conversion."""

import json

from slash.core.models import AppInstallOut, SessionOut, SnapshotOut, StepOut, TaskOut
from slash.store.tables import AppInstallRow, SessionRow, SnapshotRow, StepRow, TaskRow


def task_out(row: TaskRow, *, takeover_id: str | None = None) -> TaskOut:
    result = json.loads(row.result_json) if row.result_json else None
    return TaskOut(
        id=row.id,
        device_id=row.device_id,
        session_id=row.session_id,
        goal=row.goal,
        mode=row.mode,
        provider=row.provider,
        status=row.status,
        result=result,
        error=row.error,
        max_steps=row.max_steps,
        steps_used=row.steps_used,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_cny=row.cost_cny,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        takeover_url=row.takeover_url or None,
        takeover_id=takeover_id,
    )


def task_out_from(store, row: TaskRow) -> TaskOut:
    takeover_id = None
    for item in store.list_open_takeovers():
        if item.task_id == row.id:
            takeover_id = item.id
            break
    return task_out(row, takeover_id=takeover_id)


def step_out(row: StepRow) -> StepOut:
    return StepOut(
        id=row.id,
        task_id=row.task_id,
        idx=row.idx,
        observation_ref=row.observation_ref,
        screenshot_ref=row.screenshot_ref,
        screenshot_url=f"/api/v1/tasks/{row.task_id}/steps/{row.idx}/screenshot",
        action=json.loads(row.action_json or "{}"),
        reasoning_summary=row.reasoning_summary,
        latency_ms=row.latency_ms,
        llm_usage=json.loads(row.llm_usage_json or "{}"),
        error=row.error,
    )


def snapshot_out(row: SnapshotRow) -> SnapshotOut:
    return SnapshotOut(
        id=row.id,
        device_id=row.device_id,
        path=row.path,
        size_bytes=row.size_bytes,
        encrypted=row.encrypted,
        created_at=row.created_at,
        note=row.note,
    )


def app_out(row: AppInstallRow) -> AppInstallOut:
    return AppInstallOut(
        id=row.id,
        device_id=row.device_id,
        package=row.package,
        apk_sha256=row.apk_sha256,
        cert_sha256=row.cert_sha256,
        installed_at=row.installed_at,
    )


def session_out(row: SessionRow) -> SessionOut:
    return SessionOut(
        id=row.id,
        device_id=row.device_id,
        created_at=row.created_at,
        context=json.loads(row.context_json or "{}"),
    )
