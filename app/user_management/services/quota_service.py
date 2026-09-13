"""Daily upload allowance.

Full rules in app/user_management/docs/quota_rules.md. In short:
  - rolling 24-hour window, reset lazily on read (no cron job)
  - the row is locked while checking so concurrent uploads cannot overshoot
  - the cap is per account, so a paid plan can raise it by writing one column

NOTE: this table is slated to move — the usage counter to document_management
and the cap to billing (tracker, structural refactor #4). Callers go through
this service rather than the model so that move touches one file.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.clock import ensure_utc, utcnow
from app.shared.exceptions import NotFoundError, QuotaExceededError
from app.user_management.models.quota import UploadQuota

WINDOW = timedelta(days=1)


class UploadQuotaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def status(self, account_id: uuid.UUID) -> UploadQuota:
        """Current allowance, with an expired window rolled over first so the
        client never shows a reset time that has already passed."""
        quota = await self._load(account_id, lock=False)
        self._roll(quota)
        await self.db.flush()
        return quota

    async def consume(self, account_id: uuid.UUID) -> None:
        """Take one upload from today's allowance, or raise 429.

        Runs inside the upload's transaction: if storing the file or writing
        the document fails afterwards, the increment rolls back with it, so a
        failed upload never costs quota.
        """
        quota = await self._load(account_id, lock=True)
        self._roll(quota)

        if quota.files_used_today >= quota.cap_files:
            reset = ensure_utc(quota.period_reset_at)
            raise QuotaExceededError(
                f"You've used all {quota.cap_files} uploads for today. "
                f"You can upload again after {reset:%d %b %Y, %H:%M} UTC."
            )

        quota.files_used_today += 1
        await self.db.flush()

    async def _load(self, account_id: uuid.UUID, lock: bool) -> UploadQuota:
        stmt = select(UploadQuota).where(UploadQuota.account_id == account_id)
        if lock:
            # Serialises concurrent uploads for one account; without it two
            # requests can both read 9-of-10 and both succeed.
            stmt = stmt.with_for_update()
        quota = await self.db.scalar(stmt)
        if quota is None:
            raise NotFoundError("Upload allowance not found for this account")
        return quota

    @staticmethod
    def _roll(quota: UploadQuota) -> None:
        now = utcnow()
        if now >= ensure_utc(quota.period_reset_at):
            quota.files_used_today = 0
            quota.period_reset_at = now + WINDOW
