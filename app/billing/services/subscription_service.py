"""Subscription service — the SAMPLE FLOW for billing.

`list_active` is the reference implementation. It demonstrates the module's
central rule: an active subscription is one whose `expires_at` is in the
future, evaluated at READ time. There is no is_active column and no job that
maintains one.

See app/billing/docs/subscription_model.md for the full lifecycle spec, and
docs/limits_and_gating.md for the FeatureGate contract that is not built yet.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models.subscription import Subscription
from app.billing.schemas.subscription import SubscriptionResponse


class SubscriptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_active(self, account_id: uuid.UUID) -> list[SubscriptionResponse]:
        """The caller's currently-usable subscriptions.

        Note `cancelled_at` is deliberately NOT part of the filter. A cancelled
        subscription stays usable until the paid period ends (PRD §8.4), so it
        must still appear here while `expires_at` is in the future.
        """
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.account_id == account_id,
                Subscription.expires_at > datetime.now(UTC),
            )
        )
        return [SubscriptionResponse.model_validate(s) for s in result.scalars().all()]
