import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

PERMISSIONS = ("view", "download")


class ShareGrant(Base):
    """Grants a GROUP access to a document. Never per-user.

    A grant is active while revoked_at IS NULL. Revocation is soft so the
    access log stays interpretable after the fact.

    `download` implies `view` — the two values are a ladder, not a set.

    See docs/sharing_and_access.md for the permission resolution algorithm.
    """

    __tablename__ = "share_grants"

    __table_args__ = (
        # Permission resolution joins grants -> memberships on group_id.
        Index("ix_share_grants_document_active", "document_id", "revoked_at"),
        Index("ix_share_grants_group_active", "group_id", "revoked_at"),
        # NOTE: enforce one ACTIVE grant per (document, group) with a partial
        # unique index. Add this by hand in the migration — SQLAlchemy cannot
        # express `WHERE revoked_at IS NULL` in a UniqueConstraint:
        #   CREATE UNIQUE INDEX uq_active_grant ON share_grants
        #     (document_id, group_id) WHERE revoked_at IS NULL;
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    permission: Mapped[str] = mapped_column(
        Enum(*PERMISSIONS, name="share_permission"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column()
