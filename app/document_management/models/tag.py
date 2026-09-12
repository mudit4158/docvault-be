import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Tag(Base):
    """A shared label catalogue — not per-user rows.

    Seeded labels: Favourites, Identity Proof, Medical, Home.

    Tagging a document resolves-or-creates the Tag, then inserts a DocTag.
    Removing a tag deletes only the DocTag join, never the Tag.
    """

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
