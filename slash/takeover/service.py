"""Issue, consume, and release takeover links. The raw token is not stored."""

from datetime import UTC, datetime

from slash.core.config import TakeoverConfig
from slash.core.errors import ConflictError, NotFoundError, TokenError
from slash.core.models import TakeoverOut
from slash.store.blobstore import BlobStore
from slash.store.db import Store
from slash.store.ids import new_id
from slash.store.tables import TakeoverRow
from slash.store.timeutil import as_utc, utcnow
from slash.takeover.recorder import Recorder
from slash.takeover.tokens import TokenService, hash_token


def _as_utc(moment: datetime) -> datetime:
    return as_utc(moment)


class TakeoverService:
    def __init__(
        self,
        *,
        config: TakeoverConfig,
        public_base_url: str,
        tokens: TokenService,
        store: Store,
        blobs: BlobStore,
        recorder: Recorder | None = None,
        record: bool | None = None,
    ) -> None:
        self.config = config
        self.public_base_url = public_base_url.rstrip("/")
        self.tokens = tokens
        self.store = store
        self.blobs = blobs
        self.recorder = recorder
        self.record = config.record if record is None else record
        # takeover id -> serial, so release can stop the recording.
        self._serials: dict[str, str] = {}

    def issue(self, *, device_id: str, task_id: str | None, reason: str, serial: str = "") -> TakeoverOut:
        token, claims = self.tokens.issue(device_id, task_id or "")
        takeover_id = new_id()
        expires = datetime.fromtimestamp(claims.exp, tz=UTC).replace(microsecond=0)
        url = f"{self.public_base_url}/takeover/{token}/"
        row = self.store.insert_takeover(
            TakeoverRow(
                id=takeover_id,
                task_id=task_id,
                device_id=device_id,
                token_hash=hash_token(token),
                expires_at=expires,
                reason=reason,
                url=url,
            )
        )
        if self.record and self.recorder is not None and serial:
            self._serials[row.id] = serial
            self.recorder.start(serial, row.id)
        return TakeoverOut(
            id=row.id,
            device_id=device_id,
            task_id=task_id,
            url=url,
            expires_at=expires,
            reason=reason,
        )

    def verify(self, token: str, *, now: datetime | None = None) -> TakeoverRow:
        """Check the signature and consume the token. A second call is a replay."""
        moment = _as_utc(now or utcnow())
        claims = self.tokens.verify(token, now=int(moment.timestamp()))
        row = self.store.get_takeover_by_hash(hash_token(token))
        if row is None:
            raise TokenError("unknown takeover token")
        if row.device_id != claims.device_id:
            raise TokenError("takeover token is for a different device")
        if as_utc(row.expires_at) < moment:
            raise TokenError("takeover token expired")
        if row.opened_at is not None:
            raise TokenError("takeover token was already used")
        row.opened_at = moment
        self.store.save_takeover(row)
        return row

    def cookie_for(self, row: TakeoverRow) -> str:
        exp = int(as_utc(row.expires_at).timestamp())
        return self.tokens.session_cookie(row.id, exp)

    def verify_cookie(self, cookie: str, *, now: datetime | None = None) -> TakeoverRow:
        moment = _as_utc(now or utcnow())
        takeover_id, _exp = self.tokens.verify_cookie(cookie, now=int(moment.timestamp()))
        row = self.store.get_takeover(takeover_id)
        if row is None or row.opened_at is None:
            raise TokenError("takeover session is not open")
        if as_utc(row.expires_at) < moment:
            raise TokenError("takeover session expired")
        return row

    async def release(self, takeover_id: str) -> TakeoverRow:
        row = self.store.require_takeover(takeover_id)
        if row.released_at is not None:
            raise ConflictError("takeover is already released")
        serial = self._serials.pop(row.id, "")
        if self.record and self.recorder is not None and serial:
            from pathlib import Path

            dest = Path(self.blobs.root) / "takeover" / f"{row.id}.mp4"
            try:
                row.recording_ref = await self.recorder.stop(serial, row.id, dest)
            except Exception:
                row.recording_ref = ""
        row.released_at = utcnow()
        self.store.save_takeover(row)
        return row

    def release_for_task(self, task_id: str) -> None:
        for row in self.store.list_open_takeovers():
            if row.task_id == task_id and row.released_at is None:
                row.released_at = utcnow()
                self.store.save_takeover(row)

    def apply_timeouts(self, now: datetime | None = None) -> list[str]:
        from slash.core.models import TaskStatus, assert_transition

        failed: list[str] = []
        for task_id in self.expire_due(now):
            task = self.store.get_task(task_id)
            if task is None or task.status != TaskStatus.NEED_HUMAN.value:
                continue
            assert_transition(task.status, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED.value
            task.error = "takeover timeout"
            task.finished_at = utcnow()
            self.store.save_task(task)
            failed.append(task_id)
        return failed

    def expire_due(self, now: datetime | None = None) -> list[str]:
        moment = _as_utc(now or utcnow())
        task_ids: list[str] = []
        for row in self.store.list_open_takeovers():
            if as_utc(row.expires_at) > moment:
                continue
            row.released_at = moment
            self.store.save_takeover(row)
            if row.task_id:
                task_ids.append(row.task_id)
        return task_ids

    def require(self, takeover_id: str) -> TakeoverRow:
        row = self.store.get_takeover(takeover_id)
        if row is None:
            raise NotFoundError(f"takeover {takeover_id} not found")
        return row
