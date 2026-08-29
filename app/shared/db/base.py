from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative base for all SQLAlchemy models.

    Every model in every module inherits from this. Alembic's autogenerate
    reads `Base.metadata` to discover all tables — make sure every model
    module is imported in `alembic/env.py`, or its table is silently missing
    from the generated migration.

    `type_annotation_map` makes every `Mapped[datetime]` column TIMEZONE-AWARE.
    This is deliberate and load-bearing: the codebase compares stored timestamps
    against `datetime.now(timezone.utc)` (subscription expiry, quota reset,
    retention windows). Comparing an aware datetime against a naive column
    raises on PostgreSQL, so the default must not be naive.
    """

    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }
