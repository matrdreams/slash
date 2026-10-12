"""Domain enums, the task state machine, and API bodies."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DeviceState(StrEnum):
    CREATED = "CREATED"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    UNHEALTHY = "UNHEALTHY"
    DELETED = "DELETED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    NEED_HUMAN = "NEED_HUMAN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_TASK_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}

ACTIVE_TASK_STATUSES = {
    TaskStatus.PENDING,
    TaskStatus.PREPARING,
    TaskStatus.RUNNING,
    TaskStatus.NEED_HUMAN,
}

# CANCELLED is allowed from every non-terminal state so POST /tasks/{id}:cancel
# works while a task is pending, preparing, or waiting on a person. The diagram
# in the spec draws the running-path cancel; the API requires the rest.
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.PREPARING, TaskStatus.CANCELLED},
    TaskStatus.PREPARING: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.NEED_HUMAN,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.NEED_HUMAN: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def assert_transition(src: TaskStatus | str, dst: TaskStatus | str) -> None:
    from slash.core.errors import InvalidTransition

    source = TaskStatus(src)
    target = TaskStatus(dst)
    if target not in _TRANSITIONS[source]:
        raise InvalidTransition(f"cannot move task from {source.value} to {target.value}")


class DeviceCreate(BaseModel):
    name: str
    image: str | None = None
    android: str = "12"
    resolution: str | None = None
    dpi: int | None = None
    mem: str | None = None
    cpus: float | None = None
    proxy: str | None = None
    fps: int | None = None
    gpu_mode: str | None = None
    fingerprint_props: dict[str, str] = Field(default_factory=dict)


class DeviceRuntimeState(BaseModel):
    state: str
    running: bool = False
    boot_completed: bool | None = None
    oom: bool = False
    detail: str = ""


class DeviceOut(BaseModel):
    id: str
    name: str
    state: str
    image: str
    android: str
    width: int
    height: int
    dpi: int
    mem: str
    cpus: float
    adb_port: int
    adb_serial: str
    data_path: str
    proxy: str | None = None
    runtime: DeviceRuntimeState | None = None


class SnapshotOut(BaseModel):
    id: str
    device_id: str
    path: str
    size_bytes: int
    encrypted: bool
    created_at: datetime
    note: str = ""


class AppInstallIn(BaseModel):
    source_url: str | None = None
    sha256: str | None = None
    expected_cert_sha256: str
    package: str | None = None


class AppInstallOut(BaseModel):
    id: str
    device_id: str
    package: str
    apk_sha256: str
    cert_sha256: str
    installed_at: datetime


class TaskCreate(BaseModel):
    device_id: str
    goal: str
    app: str | None = None
    max_steps: int | None = None
    mode: str | None = None
    provider: str | None = None
    require_confirm: bool | None = None
    session_id: str | None = None
    max_cost_cny: float | None = None


class TaskOut(BaseModel):
    id: str
    device_id: str
    session_id: str | None = None
    goal: str
    mode: str
    provider: str
    status: str
    result: dict[str, Any] | None = None
    error: str = ""
    max_steps: int
    steps_used: int
    tokens_in: int
    tokens_out: int
    cost_cny: float
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    takeover_url: str | None = None
    takeover_id: str | None = None


class StepOut(BaseModel):
    id: str
    task_id: str
    idx: int
    observation_ref: str
    screenshot_ref: str
    screenshot_url: str
    action: dict[str, Any]
    reasoning_summary: str
    latency_ms: int
    llm_usage: dict[str, Any]
    error: str = ""


class ReplyIn(BaseModel):
    text: str


class SessionCreate(BaseModel):
    device_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: str
    device_id: str
    created_at: datetime
    context: dict[str, Any]


class TakeoverOut(BaseModel):
    id: str
    device_id: str
    task_id: str | None = None
    url: str
    expires_at: datetime
    reason: str = ""
