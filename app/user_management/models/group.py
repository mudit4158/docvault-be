import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Membership(Base):
    """Account ↔ Group join. Role is either "admin" or "member".

    There must always be exactly one admin per group.
    See docs/group_rules.md for invariant enforcement details.
    """

    __tablename__ = "memberships"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        Enum("admin", "member", name="membership_role"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Invitation(Base):
    """Pending, accepted, or declined invite from a group admin to an account.

    A user can have at most one non-declined invitation per group.
    """

    __tablename__ = "invitations"

    __table_args__ = (
        UniqueConstraint("group_id", "invited_user_id", name="uq_invitation_group_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "declined", name="invitation_status"),
        default="pending",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
