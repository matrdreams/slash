"""Naive UTC timestamps so SQLite round-trips stay comparable."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
