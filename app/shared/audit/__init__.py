"""Generic, pluggable audit framework.

Two halves, deliberately independent:

  CAPTURE   `listeners.py` — SQLAlchemy session events turn every INSERT,
            UPDATE and DELETE on an audited model into an `AuditRecord`.
  STORAGE   `sinks/` — an `AuditSink` decides where records go.

Swapping storage never touches capture. `PerTableSink` (the default) writes a
shadow table per audited table with typed columns; `SingleTableSink` writes one
shared JSON table. A new sink is a subclass plus a `register_sink` call.

Opting a model in:

    class Group(Base):
        __audited__ = True
        __audit_exclude__ = {"some_sensitive_column"}   # optional

Services never call the audit layer.

Audit tables are generated from the models, so they must be installed AFTER
every model module is imported. `app/registry.py` guarantees that ordering —
import it rather than calling `install_audit_tables()` yourself.

Note this is NOT `AccessLog` in document_management. That is a product feature
(PRD §4.8): per-document, read and exported by the document's owner. This is
infrastructure covering every audited table, with no UI surface.
"""

from app.shared.audit import listeners  # noqa: F401  (registers the session events)
from app.shared.audit.context import acting_as, get_actor, reset_actor, set_actor
from app.shared.audit.listeners import configure_audit, current_sink
from app.shared.audit.record import AuditRecord
from app.shared.audit.registry import (
    audit_table_for,
    audited_models,
    install_audit_tables,
)
from app.shared.audit.sinks import AuditSink, NullSink, PerTableSink, get_sink, register_sink

__all__ = [
    "AuditRecord",
    "AuditSink",
    "NullSink",
    "PerTableSink",
    "acting_as",
    "audit_table_for",
    "audited_models",
    "configure_audit",
    "current_sink",
    "get_actor",
    "get_sink",
    "install_audit_tables",
    "register_sink",
    "reset_actor",
    "set_actor",
]
