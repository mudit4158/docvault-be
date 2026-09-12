"""Audit sink selection.

Which sink is active comes from `settings.audit_sink`, so the storage strategy
is a deployment choice rather than a code change.
"""

from app.shared.audit.sinks.base import AuditSink, NullSink
from app.shared.audit.sinks.per_table import PerTableSink

_SINKS: dict[str, type[AuditSink]] = {
    PerTableSink.name: PerTableSink,
    NullSink.name: NullSink,
}


def register_sink(sink_cls: type[AuditSink]) -> None:
    """Add a sink implementation. Call before the app configures auditing."""
    _SINKS[sink_cls.name] = sink_cls


def get_sink(name: str) -> AuditSink:
    if name == "single_table":
        # Imported lazily: defining its module registers `audit_logs` on
        # Base.metadata, and that table should not exist unless the sink is
        # actually selected.
        from app.shared.audit.sinks.single_table import SingleTableSink

        register_sink(SingleTableSink)

    sink_cls = _SINKS.get(name)
    if sink_cls is None:
        raise ValueError(
            f"Unknown audit sink {name!r}. Available: {sorted(_SINKS)} plus 'single_table'."
        )
    return sink_cls()


__all__ = ["AuditSink", "NullSink", "PerTableSink", "get_sink", "register_sink"]
