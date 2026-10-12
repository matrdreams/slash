"""Local blob directory for screenshots, UI trees, and takeover recordings."""

from datetime import datetime, timedelta
from pathlib import Path

from slash.store.timeutil import utcnow


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, *parts: str, data: bytes) -> str:
        if not parts:
            raise ValueError("blob path is empty")
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get(self, ref: str) -> bytes:
        return Path(ref).read_bytes()

    def purge_older_than(self, days: int, now: datetime | None = None) -> int:
        if days < 0:
            return 0
        cutoff = (now or utcnow()) - timedelta(days=days)
        removed = 0
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified < cutoff:
                path.unlink()
                removed += 1
        return removed
