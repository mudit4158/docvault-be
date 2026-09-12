"""Change capture via SQLAlchemy session events.

Services never call this. Any model declaring `__audited__ = True` has every
INSERT, UPDATE and DELETE captured automatically, which removes the standard
failure mode of manual audit logging: one forgotten call leaving a silent hole
that no review catches.

Capture is separate from storage. This module only produces `AuditRecord`s and
hands them to the configured `AuditSink` — see `sinks/`.

Two hooks, because neither alone has everything needed:

  before_flush  attribute history is intact, so old values are readable — but
                a client-side-default primary key is not yet populated.
  after_flush   primary keys are populated, but history has been reset.

So `before_flush` captures the diff and stashes it, `after_flush` resolves the
primary keys and emits.
"""

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.shared.audit.context import get_actor
from app.shared.audit.record import AuditRecord
from app.shared.audit.registry import (
    coerce,
    excluded_fields,
    is_audited,
    record_id_of,
)
from app.shared.audit.sinks import AuditSink, PerTableSink

_PENDING_KEY = "_audit_pending"

# Replaced at startup by configure_audit(). Defaults to the per-table sink so
# importing the package alone gives working audit.
_sink: AuditSink = PerTableSink()


def configure_audit(sink: AuditSink) -> None:
    """Point the listeners at a different sink. Call once, at startup."""
    global _sink
    _sink = sink


def current_sink() -> AuditSink:
    return _sink


def _snapshot(obj: object, exclude: set[str]) -> dict[str, Any]:
    """Full current column state, minus excluded columns.

    Values stay native — the per-table sink writes them into typed columns.
    """
    return {
        attr.key: getattr(obj, attr.key)
        for attr in inspect(type(obj)).column_attrs
        if attr.key not in exclude
    }


def _diff(obj: object, exclude: set[str]) -> tuple[list[str], dict[str, Any]]:
    """Changed column names and their prior values."""
    state = inspect(obj)
    changed: list[str] = []
    old: dict[str, Any] = {}

    for attr in inspect(type(obj)).column_attrs:
        if attr.key in exclude:
            continue
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        changed.append(attr.key)
        # `deleted` holds the prior value; empty when a column is being set for
        # the first time, which is a legitimate "was null".
        old[attr.key] = coerce(history.deleted[0]) if history.deleted else None

    return changed, old


@event.listens_for(Session, "before_flush")
def _capture_changes(session: Session, flush_context: Any, instances: Any) -> None:
    pending: list[dict[str, Any]] = session.info.setdefault(_PENDING_KEY, [])

    for obj in session.new:
        if not is_audited(obj):
            continue
        exclude = excluded_fields(type(obj))
        pending.append(
            {
                "obj": obj,
                "table_name": obj.__tablename__,
                "operation": "INSERT",
                "changed_fields": None,
                "old_values": None,
                "snapshot": _snapshot(obj, exclude),
                "resolve_pk": True,
            }
        )

    for obj in session.dirty:
        if not is_audited(obj) or not session.is_modified(obj):
            continue
        exclude = excluded_fields(type(obj))
        changed, old = _diff(obj, exclude)
        if not changed:
            # Touched but nothing actually differs. Writing a row here would
            # fill the trail with entries that describe no change.
            continue
        pending.append(
            {
                "obj": obj,
                "table_name": obj.__tablename__,
                "operation": "UPDATE",
                "changed_fields": changed,
                "old_values": old,
                "snapshot": _snapshot(obj, exclude),
                "resolve_pk": True,
            }
        )

    for obj in session.deleted:
        if not is_audited(obj):
            continue
        exclude = excluded_fields(type(obj))
        pending.append(
            {
                "obj": obj,
                "table_name": obj.__tablename__,
                "operation": "DELETE",
                "changed_fields": None,
                "old_values": None,
                # Before-image: the state being destroyed is the state worth
                # keeping. Read now, because the row is gone after the flush.
                "snapshot": _snapshot(obj, exclude),
                "record_id": record_id_of(obj),
                "resolve_pk": False,
            }
        )


@event.listens_for(Session, "after_flush")
def _emit(session: Session, flush_context: Any) -> None:
    pending: list[dict[str, Any]] = session.info.get(_PENDING_KEY) or []
    if not pending:
        return
    # Clear before emitting. The sinks use Core INSERTs which do not re-enter
    # the unit of work, but clearing first keeps this re-entrancy-safe whatever
    # a custom sink does.
    session.info[_PENDING_KEY] = []

    actor_id = get_actor()
    records = [
        AuditRecord(
            table_name=entry["table_name"],
            record_id=(
                record_id_of(entry["obj"]) if entry["resolve_pk"] else entry["record_id"]
            ),
            operation=entry["operation"],
            snapshot=entry["snapshot"],
            changed_fields=entry["changed_fields"],
            old_values=entry["old_values"],
            actor_id=actor_id,
        )
        for entry in pending
    ]

    _sink.emit(session, records)
