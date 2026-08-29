import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

ACCESS_EVENTS = (
    "upload",
    "view",
    "download",
    "share",
    "revoke",
    "delete",
    "restore",
    "rename",
)


class AccessLog(Base):
    """APPEND-ONLY audit trail. Never UPDATE. Never DELETE.

    The log outlives the file: the hard-delete job purges storage and nulls
    Document.storage_key, but leaves every row here intact (PRD §4.3).

    Note the FKs deliberately do NOT cascade-delete from documents — a log row
    must survive its document. actor_id is SET NULL on account deletion so the
    trail survives an account being removed.

    See docs/access_log.md.
    """

    __tablename__ = "access_logs"

    __table_args__ = (
        # Owner reads the log newest-first, per document.
        Index("ix_access_logs_document_created", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="NO ACTION"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(
        Enum(*ACCESS_EVENTS, name="access_event_type"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
