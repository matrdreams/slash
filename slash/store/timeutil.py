"""UTC timestamps. SQLAlchemy 2 rejects naive values on write."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
