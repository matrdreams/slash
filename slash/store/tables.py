"""SQLModel tables. Timestamps are naive UTC."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from slash.store.timeutil import utcnow


class UserRow(SQLModel, table=True):
    __tablename__ = "user"
    id: str = Field(primary_key=True)
    name: str
    api_token_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class ProxyProfileRow(SQLModel, table=True):
    __tablename__ = "proxy_profile"
    id: str = Field(primary_key=True)
    type: str = "static"
    host: str = ""
    port: int = 0
    exclude_list: str = ""
    egress_ip_note: str = ""


class DeviceRow(SQLModel, table=True):
    __tablename__ = "device"
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    name: str = Field(index=True)
    backend: str
    image: str
    android_version: str = "12"
    width: int = 720
    height: int = 1280
    dpi: int = 320
    fps: int = 15
    gpu_mode: str = "guest"
    mem: str = "3g"
    mem_mb: int = 3072
    cpus: float = 2
    dns_json: str = '["223.5.5.5"]'
    use_memfd: bool = True
    adb_port: int
    data_path: str
    proxy: str | None = None
    proxy_profile_id: str | None = None
    state: str = "CREATED"
    last_active_at: datetime | None = None
    fingerprint_props: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)
    provisioned: bool = False
    seq: int = 0
    overlayfs: bool = False


class SnapshotRow(SQLModel, table=True):
    __tablename__ = "snapshot"
    id: str = Field(primary_key=True)
    device_id: str = Field(index=True)
    path: str
    size_bytes: int = 0
    encrypted: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    note: str = ""


class AppInstallRow(SQLModel, table=True):
    __tablename__ = "app_install"
    id: str = Field(primary_key=True)
    device_id: str = Field(index=True)
    package: str
    version_name: str = ""
    apk_sha256: str
    cert_sha256: str
    installed_at: datetime = Field(default_factory=utcnow)


class SessionRow(SQLModel, table=True):
    __tablename__ = "session"
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    device_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    context_json: str = "{}"


class TaskRow(SQLModel, table=True):
    __tablename__ = "task"
    id: str = Field(primary_key=True)
    session_id: str | None = Field(default=None, index=True)
    device_id: str = Field(index=True)
    goal: str
    app: str | None = None
    mode: str = "tree+vision"
    provider: str = ""
    status: str = "PENDING"
    result_json: str = ""
    error: str = ""
    max_steps: int = 40
    steps_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cny: float = 0.0
    max_cost_cny: float | None = None
    require_confirm: bool = True
    human_reply: str = ""
    takeover_url: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class StepRow(SQLModel, table=True):
    __tablename__ = "step"
    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    idx: int
    observation_ref: str = ""
    screenshot_ref: str = ""
    action_json: str = "{}"
    reasoning_summary: str = ""
    latency_ms: int = 0
    llm_usage_json: str = "{}"
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class TaskEventRow(SQLModel, table=True):
    __tablename__ = "task_event"
    id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    seq: int
    event: str
    data_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)


class TakeoverRow(SQLModel, table=True):
    __tablename__ = "takeover"
    id: str = Field(primary_key=True)
    task_id: str | None = Field(default=None, index=True)
    device_id: str = Field(index=True)
    token_hash: str = Field(index=True)
    expires_at: datetime
    opened_at: datetime | None = None
    released_at: datetime | None = None
    recording_ref: str = ""
    reason: str = ""
    url: str = ""


class AuditEventRow(SQLModel, table=True):
    __tablename__ = "audit_event"
    id: str = Field(primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    actor: str = "local"
    kind: str
    target: str = ""
    detail_json: str = "{}"
