import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Tag(Base):
    """A shared label catalogue — not per-user rows.

    Seeded labels: Favourites, Identity Proof, Medical, Home.
    Adding a tag to a document resolves-or-creates the Tag, then inserts a DocTag.
    Removing a tag deletes only the DocTag join, never the Tag itself.
    """

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocTag(Base):
    """Document ↔ Tag join. A document may carry many tags."""

    __tablename__ = "doc_tags"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
