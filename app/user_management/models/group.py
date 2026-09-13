import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Group(Base):
    """A named circle of people documents can be shared into.

    Flat — no sub-groups, no folders (engineering handoff §2).
    Membership and invitations are separate models; see `membership.py` and
    `invitation.py`.
    """

    __tablename__ = "groups"
    __audited__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    # SET NULL rather than CASCADE: deleting the creator's account must not
    # delete a group other people still belong to.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
