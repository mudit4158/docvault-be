"""Where audit records go.

The listeners capture changes and hand `AuditRecord`s to a sink. Swapping the
sink changes the storage strategy without touching capture, and vice versa.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.shared.audit.record import AuditRecord


class AuditSink(ABC):
    """Persists audit records.

    Implementations run inside the flush of the transaction that produced the
    change, so an audit row commits or rolls back with the work it describes.
    A sink must therefore be cheap and must not perform I/O that could block
    the transaction — an external sink should enqueue, not call out.
    """

    name: str

    @abstractmethod
    def emit(self, session: Session, records: Sequence[AuditRecord]) -> None:
        """Write the records. Called once per flush with everything captured."""


class NullSink(AuditSink):
    """Discards everything. For tests and for disabling audit outright."""

    name = "none"

    def emit(self, session: Session, records: Sequence[AuditRecord]) -> None:
        return None
