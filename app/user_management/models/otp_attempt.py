from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class OtpAttempt(Base):
    """Throttles OTP login attempts against a phone number with no matching account.

    Keyed by phone, not account_id — the whole point is that no Account may
    exist yet for this number. A valid Firebase token already proves phone
    ownership, so the only thing left to protect against is someone using a
    number they control to probe which phone numbers hold a DocVault account
    (see docs/auth_flow.md). A malformed/expired/forged token never reaches
    this table at all — that failure has no phone number to attribute it to,
    and forging a valid-looking Firebase token is not a realistic attack this
    needs to defend against.

    Reset to zero on the first login that DOES match an account for this
    phone, so a legitimate user who registers after a few failed OTP attempts
    isn't punished for it.
    """

    __tablename__ = "otp_attempts"
    __audited__ = True

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
