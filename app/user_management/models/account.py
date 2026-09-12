import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class Account(Base):
    """A person's identity. Deliberately holds NO credentials.

    How an account proves who it is lives in `AuthIdentity` — one row per
    login method. That split is what lets OTP and SSO be added later as new
    rows rather than new columns here.

    See docs/auth_flow.md.
    """

    __tablename__ = "accounts"
    __audited__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    # Shown wherever a person appears in the UI — member rows, "Invited by
    # Anita" on the invitations screen.
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
