import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class UploadQuota(Base):
    """Tracks how many files a user has uploaded today.

    Created alongside every Account. One row per account (primary key = account_id).
    The document_management module reads and increments this on every successful upload.
    """

    __tablename__ = "upload_quotas"
    __audited__ = True

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    files_used_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_reset_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # cap_files can be raised by a paid plan (billing module overrides this)
    cap_files: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
