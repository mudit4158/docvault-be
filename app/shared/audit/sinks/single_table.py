"""Every change in one shared `audit_logs` table.

Not the default. Kept because it is a genuinely different trade-off, and
because having a second implementation is what proves the sink abstraction is
real rather than decorative:

  per_table    typed columns, cheap queries, schema grows with the model count
  single_table one table, JSON values, needs partitioning early, easy to ship
               off-box wholesale

Select with `AUDIT_SINK=single_table`.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, String, Table, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.shared.audit.record import AuditRecord
from app.shared.audit.registry import coerce
from app.shared.audit.sinks.base import AuditSink
from app.shared.db.base import Base

JSONVariant = JSON().with_variant(JSONB, "postgresql")

audit_logs_table = Table(
    "audit_logs",
    Base.metadata,
    Column("id", Uuid, primary_key=True, default=uuid.uuid4),
    Column("table_name", String(64), nullable=False),
    Column("record_id", String(256), nullable=False),
    Column("operation", String(8), nullable=False),
    Column("changed_fields", JSONVariant, nullable=True),
    Column("old_values", JSONVariant, nullable=True),
    Column("new_values", JSONVariant, nullable=True),
    Column("actor_id", Uuid, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Index("ix_audit_logs_record", "table_name", "record_id"),
    Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
)


class SingleTableSink(AuditSink):
    name = "single_table"

    def emit(self, session: Session, records: Sequence[AuditRecord]) -> None:
        if not records:
            return

        rows = [
            {
                "id": uuid.uuid4(),
                "table_name": r.table_name,
                "record_id": r.record_id,
                "operation": r.operation,
                "changed_fields": r.changed_fields,
                "old_values": (
                    {k: coerce(v) for k, v in r.old_values.items()} if r.old_values else None
                ),
                "new_values": (
                    {k: coerce(v) for k, v in r.snapshot.items()}
                    if r.operation != "DELETE"
                    else None
                ),
                "actor_id": r.actor_id,
            }
            for r in records
        ]
        session.execute(audit_logs_table.insert(), rows)


__all__ = ["SingleTableSink", "audit_logs_table", "datetime"]
