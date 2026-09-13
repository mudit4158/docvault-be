import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

INVITATION_STATUSES = ("pending", "accepted", "declined")


class Invitation(Base):
    """An invitation from a group admin to an existing account.

    Group invites only reach people who already have a DocVault account —
    inviting someone to the platform is future scope.

    The unique constraint means a declined invitation is REOPENED in place on
    re-invite rather than duplicated, so one row holds the whole history of
    that pairing.
    """

    __tablename__ = "invitations"
    __audited__ = True

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
    # SET NULL: the invitation outlives the inviter's account.
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum(*INVITATION_STATUSES, name="invitation_status"),
        default="pending",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
