"""The transport-neutral shape of one audited change.

Listeners produce these; sinks consume them. Neither knows about the other,
which is what makes the storage strategy swappable.
"""

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditRecord:
    """One INSERT, UPDATE or DELETE against an audited table."""

    table_name: str
    """Source table, e.g. "accounts"."""

    record_id: str
    """Stringified source primary key. Composite keys render "col=val,col=val"."""

    operation: str
    """INSERT | UPDATE | DELETE."""

    snapshot: dict[str, Any]
    """Full column state of the row.

    After-image for INSERT and UPDATE; before-image for DELETE — i.e. always
    the state worth keeping. Excluded columns are already stripped.
    """

    changed_fields: list[str] | None
    """Columns that changed. None for INSERT and DELETE, where the whole row
    is the change."""

    old_values: dict[str, Any] | None
    """Prior values of the changed columns. Only populated for UPDATE."""

    actor_id: uuid.UUID | None
    """Account that caused the change. None for unauthenticated actions
    (registration, login) and background jobs — expected, not a bug."""
