"""One audit table per audited table — the default sink.

`accounts` changes land in `accounts_audit`, `groups` in `groups_audit`, and so
on. Columns are mirrored from the source, so values stay typed and indexable
instead of collapsing into a JSON blob.

Excluded columns are absent from the audit table entirely, so a secret cannot
reach the trail even by accident.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.shared.audit.record import AuditRecord
from app.shared.audit.registry import audit_table_for
from app.shared.audit.sinks.base import AuditSink


class PerTableSink(AuditSink):
    name = "per_table"

    def emit(self, session: Session, records: Sequence[AuditRecord]) -> None:
        if not records:
            return

        # Group by source table so each audit table takes one multi-row INSERT
        # rather than one statement per change.
        by_table: dict[str, list[AuditRecord]] = defaultdict(list)
        for record in records:
            by_table[record.table_name].append(record)

        for table_name, table_records in by_table.items():
            audit_table = audit_table_for(table_name)
            if audit_table is None:
                # Model marked __audited__ but install_audit_tables() never ran
                # for it — almost always a missing import in app/registry.py.
                continue

            audit_columns = {c.name for c in audit_table.columns}

            rows = []
            for record in table_records:
                row: dict[str, object] = {
                    "audit_id": uuid.uuid4(),
                    "audit_operation": record.operation,
                    "audit_actor_id": record.actor_id,
                    "audit_changed_fields": record.changed_fields,
                }
                # Only mirror columns the audit table actually has. A column
                # added to the model but not yet migrated into the audit table
                # is skipped rather than raising.
                for key, value in record.snapshot.items():
                    if key in audit_columns:
                        row[key] = value
                rows.append(row)

            # Core INSERT, not ORM: it must not re-enter the unit of work and
            # trigger another flush.
            session.execute(audit_table.insert(), rows)
