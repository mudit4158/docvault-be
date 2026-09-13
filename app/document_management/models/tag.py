import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Tag(Base):
    """A label catalogue row, shared across accounts for storage.

    Default suggestions: Favourites, Identity Proof, Medical, Home.

    Tagging a document resolves-or-creates the Tag (case-insensitively), then
    inserts a DocTag. Removing a tag deletes only the DocTag join, never the Tag.

    Although rows are shared, a user is only ever SHOWN labels they have used
    themselves plus the defaults — another person's labels ("Divorce papers")
    are private information. See TagService.suggestions.
    """

    __tablename__ = "tags"
    __audited__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
