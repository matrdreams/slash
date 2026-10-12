"""Session helpers around the SQLModel engine."""

import json
from typing import Any

from sqlmodel import Session, SQLModel, create_engine, select

from slash.core.errors import NotFoundError
from slash.core.models import ACTIVE_TASK_STATUSES, TaskStatus
from slash.store.ids import new_id
from slash.store.tables import (
    AppInstallRow,
    AuditEventRow,
    DeviceRow,
    ProxyProfileRow,
    SessionRow,
    SnapshotRow,
    StepRow,
    TakeoverRow,
    TaskEventRow,
    TaskRow,
    UserRow,
)


class Store:
    def __init__(self, db_url: str) -> None:
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(db_url, connect_args=connect_args)
        self.db_url = db_url

    def init_db(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def ensure_user(self, token_hash: str, name: str = "local") -> UserRow:
        with self.session() as db:
            row = db.exec(select(UserRow).where(UserRow.name == name)).first()
            if row is not None:
                row.api_token_hash = token_hash
                db.add(row)
                db.commit()
                db.refresh(row)
                return row
            row = UserRow(id=new_id(), name=name, api_token_hash=token_hash)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def audit(self, kind: str, target: str = "", detail: dict | None = None, actor: str = "local") -> None:
        with self.session() as db:
            db.add(
                AuditEventRow(
                    id=new_id(),
                    kind=kind,
                    target=target,
                    actor=actor,
                    detail_json=json.dumps(detail or {}, ensure_ascii=False),
                )
            )
            db.commit()

    def insert_device(self, row: DeviceRow) -> DeviceRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def get_device(self, device_id: str) -> DeviceRow | None:
        with self.session() as db:
            return db.get(DeviceRow, device_id)

    def require_device(self, device_id: str) -> DeviceRow:
        row = self.get_device(device_id)
        if row is None or row.state == "DELETED":
            raise NotFoundError(f"device {device_id} not found")
        return row

    def get_device_by_name(self, name: str) -> DeviceRow | None:
        with self.session() as db:
            stmt = select(DeviceRow).where(DeviceRow.name == name, DeviceRow.state != "DELETED")
            return db.exec(stmt).first()

    def list_devices(self) -> list[DeviceRow]:
        with self.session() as db:
            stmt = select(DeviceRow).where(DeviceRow.state != "DELETED")
            return list(db.exec(stmt))

    def save_device(self, row: DeviceRow) -> DeviceRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def next_seq(self) -> int:
        with self.session() as db:
            rows = list(db.exec(select(DeviceRow)))
        if not rows:
            return 1
        return max(row.seq for row in rows) + 1

    def count_state(self, state: str) -> int:
        return sum(1 for row in self.list_devices() if row.state == state)

    def insert_proxy(self, host: str, port: int) -> ProxyProfileRow:
        row = ProxyProfileRow(id=new_id(), type="static", host=host, port=port)
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def insert_task(self, row: TaskRow) -> TaskRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_tasks(self) -> list[TaskRow]:
        with self.session() as db:
            rows = list(db.exec(select(TaskRow)))
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    def get_task(self, task_id: str) -> TaskRow | None:
        with self.session() as db:
            return db.get(TaskRow, task_id)

    def require_task(self, task_id: str) -> TaskRow:
        row = self.get_task(task_id)
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return row

    def save_task(self, row: TaskRow) -> TaskRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def active_task_for_device(self, device_id: str, *, ignore: str | None = None) -> TaskRow | None:
        with self.session() as db:
            stmt = select(TaskRow).where(TaskRow.device_id == device_id)
            rows = list(db.exec(stmt))
        active = {status.value for status in ACTIVE_TASK_STATUSES}
        for row in rows:
            if ignore and row.id == ignore:
                continue
            if row.status in active:
                return row
        return None

    def insert_step(self, row: StepRow) -> StepRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_steps(self, task_id: str) -> list[StepRow]:
        with self.session() as db:
            stmt = select(StepRow).where(StepRow.task_id == task_id).order_by(StepRow.idx)
            return list(db.exec(stmt))

    def add_event(self, task_id: str, event: str, data: dict[str, Any]) -> TaskEventRow:
        with self.session() as db:
            existing = list(db.exec(select(TaskEventRow).where(TaskEventRow.task_id == task_id)))
            seq = len(existing) + 1
            row = TaskEventRow(
                id=new_id(),
                task_id=task_id,
                seq=seq,
                event=event,
                data_json=json.dumps(data, ensure_ascii=False),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_events(self, task_id: str) -> list[TaskEventRow]:
        with self.session() as db:
            stmt = select(TaskEventRow).where(TaskEventRow.task_id == task_id).order_by(TaskEventRow.seq)
            return list(db.exec(stmt))

    def insert_snapshot(self, row: SnapshotRow) -> SnapshotRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_snapshots(self, device_id: str) -> list[SnapshotRow]:
        with self.session() as db:
            stmt = select(SnapshotRow).where(SnapshotRow.device_id == device_id)
            return list(db.exec(stmt))

    def get_snapshot(self, snapshot_id: str) -> SnapshotRow | None:
        with self.session() as db:
            return db.get(SnapshotRow, snapshot_id)

    def insert_app(self, row: AppInstallRow) -> AppInstallRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_apps(self, device_id: str) -> list[AppInstallRow]:
        with self.session() as db:
            stmt = select(AppInstallRow).where(AppInstallRow.device_id == device_id)
            return list(db.exec(stmt))

    def insert_session(self, row: SessionRow) -> SessionRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def get_session(self, session_id: str) -> SessionRow | None:
        with self.session() as db:
            return db.get(SessionRow, session_id)

    def insert_takeover(self, row: TakeoverRow) -> TakeoverRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def get_takeover(self, takeover_id: str) -> TakeoverRow | None:
        with self.session() as db:
            return db.get(TakeoverRow, takeover_id)

    def require_takeover(self, takeover_id: str) -> TakeoverRow:
        row = self.get_takeover(takeover_id)
        if row is None:
            raise NotFoundError(f"takeover {takeover_id} not found")
        return row

    def get_takeover_by_hash(self, token_hash: str) -> TakeoverRow | None:
        with self.session() as db:
            stmt = select(TakeoverRow).where(TakeoverRow.token_hash == token_hash)
            return db.exec(stmt).first()

    def save_takeover(self, row: TakeoverRow) -> TakeoverRow:
        with self.session() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

    def list_open_takeovers(self) -> list[TakeoverRow]:
        with self.session() as db:
            rows = list(db.exec(select(TakeoverRow)))
        return [row for row in rows if row.released_at is None]

    def tasks_by_status(self, status: TaskStatus) -> list[TaskRow]:
        with self.session() as db:
            stmt = select(TaskRow).where(TaskRow.status == status.value)
            return list(db.exec(stmt))
