import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func
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
    as `expires_at > now()`. A job that flips a stored flag lags real expiry in
    both directions. See docs/subscription_model.md.

    `cancelled_at` stops auto-renewal but does NOT shorten expires_at: a
    cancelled subscription stays usable until the paid period ends (PRD §8.4).

    `credit_balance` is independent of expires_at — unused credits never expire
    with the subscription (PRD §8.4). Nothing in the codebase zeroes it.
    """

    __tablename__ = "subscriptions"

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


class PlanLimit(Base):
    """Per-account overrides of the configurable parameters (PRD §8.3, §9).

    Every column is NULLABLE. NULL means "fall back to the global default in
    settings" — so raising a global default automatically applies to every
    account that has not been individually raised.

    NOTE the daily upload cap is NOT here. It is written directly into
    UploadQuota.cap_files so the upload hot path stays a single locked row read.
    See docs/limits_and_gating.md.
    """

    __tablename__ = "plan_limits"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    max_upload_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    group_member_cap: Mapped[int | None] = mapped_column(Integer)
    soft_delete_retention_days: Mapped[int | None] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
