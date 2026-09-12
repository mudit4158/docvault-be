import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

FEATURE_KEYS = (
    "video_to_pdf",
    "versioning",
    "auto_doc_type",
    "group_encryption",
    "p2p_storage",
    "pdf_signing",
    "ai_editing",
    "bundle",
)


class Subscription(Base):
    """One row per (account, feature_key).

    There is deliberately NO is_active column — active is computed at read time
    as `expires_at > now()`. A job that maintains a stored flag lags real expiry
    in both directions: users keep a feature they stopped paying for, or lose
    one they paid for.

    `cancelled_at` stops auto-renewal but does NOT shorten `expires_at`: a
    cancelled subscription stays usable to the end of the paid period (PRD §8.4).

    `credit_balance` is independent of `expires_at` — unused credits never
    expire with the subscription (PRD §8.4). Nothing in the codebase zeroes it.
    """

    __tablename__ = "subscriptions"
    __audited__ = True

    __table_args__ = (
        UniqueConstraint("account_id", "feature_key", name="uq_subscription_account_feature"),
        CheckConstraint("credit_balance >= 0", name="ck_subscription_credit_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)

    credit_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
