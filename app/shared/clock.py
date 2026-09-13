"""Time helpers.

All timestamps in DocVault are UTC. PostgreSQL returns timezone-aware values
for the `DateTime(timezone=True)` columns, but SQLite (the test and local dev
database) hands them back naive. Comparing a naive value with
`datetime.now(UTC)` raises, so anything read from the database that is used in
arithmetic or comparison goes through `ensure_utc` first.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC; convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
