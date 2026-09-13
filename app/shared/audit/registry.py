"""Discovery of audited models, and generation of their audit tables.

A model opts in with one attribute:

    class Account(Base):
        __audited__ = True
        __audit_exclude__ = {"secret_hash"}   # optional

`install_audit_tables()` then builds a shadow table per audited model —
`accounts` gets `accounts_audit` — mirroring its columns so audit rows are
TYPED rather than JSON blobs.

Excluded columns are omitted from the audit table entirely. That is stronger
than filtering them at write time: the column does not exist, so a secret
cannot leak into the trail even if a future sink forgets to check.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Index,
    String,
    Table,
    Uuid,
    func,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.shared.db.base import Base

JSONVariant = JSON().with_variant(JSONB, "postgresql")

AUDIT_TABLE_SUFFIX = "_audit"

# Never mirrored into an audit table, for any model, even if it declares no
# __audit_exclude__ of its own.
ALWAYS_EXCLUDED = frozenset({"secret_hash", "password_hash", "pin_hash", "token_hash"})

# Prefix on the audit framework's own columns, so they cannot collide with a
# mirrored source column named e.g. "operation".
_AUDIT_ID = "audit_id"
_AUDIT_OPERATION = "audit_operation"
_AUDIT_ACTOR_ID = "audit_actor_id"
_AUDIT_AT = "audit_at"
_AUDIT_CHANGED_FIELDS = "audit_changed_fields"

AUDIT_COLUMN_NAMES = frozenset(
    {_AUDIT_ID, _AUDIT_OPERATION, _AUDIT_ACTOR_ID, _AUDIT_AT, _AUDIT_CHANGED_FIELDS}
)

# model class -> its audit Table
_AUDIT_TABLES: dict[type, Table] = {}
# source table name -> its audit Table (what the sinks look up)
_AUDIT_TABLES_BY_NAME: dict[str, Table] = {}


def is_audited(obj: Any) -> bool:
    return getattr(type(obj), "__audited__", False) is True


def excluded_fields(model: type) -> set[str]:
    return set(ALWAYS_EXCLUDED) | set(getattr(model, "__audit_exclude__", set()))


def _mirror_type(column: Column[Any]) -> Any:
    """The column type to use in the audit table.

    Enums become plain strings. An audit table must accept values that the
    source enum no longer allows — a role or status retired by a later
    migration still has to be readable in history — and reusing a named
    PostgreSQL enum across tables would try to CREATE TYPE twice.
    """
    if isinstance(column.type, Enum):
        return String(64)
    return column.type


def build_audit_table(model: type) -> Table:
    """Construct the audit table for one audited model."""
    source: Table = model.__table__  # type: ignore[attr-defined]
    exclude = excluded_fields(model)

    columns: list[Column[Any]] = [
        Column(_AUDIT_ID, Uuid, primary_key=True, default=uuid.uuid4),
        Column(_AUDIT_OPERATION, String(8), nullable=False),
        # No FK to accounts: an audit row must survive the account being
        # deleted, and an FK would either block the delete or cascade the row away.
        Column(_AUDIT_ACTOR_ID, Uuid, nullable=True),
        Column(_AUDIT_AT, DateTime(timezone=True), server_default=func.now(), nullable=False),
        Column(_AUDIT_CHANGED_FIELDS, JSONVariant, nullable=True),
    ]

    for col in source.columns:
        if col.name in exclude:
            continue
        columns.append(
            Column(
                col.name,
                _mirror_type(col),
                # Every mirrored column is nullable: a DELETE snapshot may be
                # partial, and a column added by a later migration has no value
                # in older audit rows.
                nullable=True,
                # No primary key, no FKs, no unique constraints, no defaults.
                # Many audit rows point at one source row, and audit rows
                # outlive the rows they describe.
            )
        )

    pk_names = [c.name for c in source.primary_key if c.name not in exclude]
    indexes = [
        # "history of this row" — the primary investigative query.
        Index(f"ix_{source.name}_audit_record", *pk_names),
        # "what did this account do", and time-range scans.
        Index(f"ix_{source.name}_audit_actor", _AUDIT_ACTOR_ID, _AUDIT_AT),
    ] if pk_names else []

    return Table(f"{source.name}{AUDIT_TABLE_SUFFIX}", Base.metadata, *columns, *indexes)


def install_audit_tables() -> dict[type, Table]:
    """Build audit tables for every audited model registered on Base.

    Idempotent, so importing the registry twice is harmless.

    MUST run after every model module has been imported, or a model's audit
    table is silently missing. `app/registry.py` is the single place that
    guarantees the ordering — import that, not this.
    """
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not getattr(model, "__audited__", False):
            continue
        if model in _AUDIT_TABLES:
            continue

        source_name = model.__table__.name  # type: ignore[attr-defined]
        audit_name = f"{source_name}{AUDIT_TABLE_SUFFIX}"

        # Another import path may have created it already.
        existing = Base.metadata.tables.get(audit_name)
        table = existing if existing is not None else build_audit_table(model)

        _AUDIT_TABLES[model] = table
        _AUDIT_TABLES_BY_NAME[source_name] = table

    return dict(_AUDIT_TABLES)


def audit_table_for(source_table_name: str) -> Table | None:
    return _AUDIT_TABLES_BY_NAME.get(source_table_name)


def audited_models() -> list[type]:
    return list(_AUDIT_TABLES)


def record_id_of(obj: Any) -> str:
    """Stringified primary key. Composite keys render "col=val,col=val"."""
    pk_columns = list(inspect(type(obj)).primary_key)
    if len(pk_columns) == 1:
        return str(getattr(obj, pk_columns[0].key))
    return ",".join(f"{c.key}={getattr(obj, c.key)}" for c in pk_columns)


def coerce(value: Any) -> Any:
    """Make a value safe for a JSON column.

    Only used for `changed_fields` and the single-table sink; per-table audit
    columns keep their native types.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)
