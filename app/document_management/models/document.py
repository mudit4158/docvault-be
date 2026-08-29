import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

DOCUMENT_TYPES = ("aadhaar", "voter_id", "pan", "passport", "other")


class Document(Base):
    """A single file in a user's vault.

    The vault is FLAT — there is deliberately no folder or parent field.

    State is derived, not stored as an enum:
        active   -> deleted_at IS NULL
        trashed  -> deleted_at IS NOT NULL, storage_key IS NOT NULL
        purged   -> deleted_at IS NOT NULL, storage_key IS NULL

    See docs/document_lifecycle.md.
    """

    __tablename__ = "documents"

    __table_args__ = (
        # The hot path: every vault listing filters on owner + not-deleted.
        Index("ix_documents_owner_active", "owner_id", "deleted_at"),
        # Default sort order.
        Index("ix_documents_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Captured at upload and never changed. Rename re-appends this, so whatever
    # extension the user types is discarded. See docs/document_lifecycle.md.
    original_extension: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    doc_type: Mapped[str] = mapped_column(
        Enum(*DOCUMENT_TYPES, name="document_type"), default="other", nullable=False
    )

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # NULL once the hard-delete job purges the file. The metadata row is retained.
    storage_key: Mapped[str | None] = mapped_column(String(512))
    thumbnail_url: Mapped[str | None] = mapped_column(String(512))

    # The only deletion signal. Never DELETE FROM documents.
    deleted_at: Mapped[datetime | None] = mapped_column(index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
