import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class PlanLimit(Base):
    """Per-account overrides of the configurable limits (PRD §8.3, §9).

    Every column is NULLABLE, and NULL means "fall back to the global default
    in settings". So raising a default automatically applies to every account
    that has not been individually raised, and a row only records the
    exceptions.

    These are ENTITLEMENTS — what a plan allows. Usage counters are a separate
    concern and live with whatever is being metered; see
    `document_management.models.upload_usage`.
    """

    __tablename__ = "plan_limits"
    __audited__ = True

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )

    daily_upload_cap: Mapped[int | None] = mapped_column(Integer)
    max_upload_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    group_member_cap: Mapped[int | None] = mapped_column(Integer)
    soft_delete_retention_days: Mapped[int | None] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
