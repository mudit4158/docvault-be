import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

MEMBERSHIP_ROLES = ("admin", "member")


class Membership(Base):
    """Account ↔ Group join, carrying the member's role.

    Composite primary key: one membership per person per group.

    Every group has exactly one admin at all times. Three paths could break
    that — admin self-removal, sole-admin leave, and admin transfer — and each
    is guarded in GroupService. See docs/group_rules.md.

    This table is also the authority for document access: permission resolution
    joins ShareGrant to Membership at query time, so adding or removing a
    member changes what they can see immediately, without touching any grant.
    """

    __tablename__ = "memberships"
    __audited__ = True

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        Enum(*MEMBERSHIP_ROLES, name="membership_role"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())
