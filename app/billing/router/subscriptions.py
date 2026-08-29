import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.schemas.subscription import SubscriptionResponse
from app.billing.services.subscription_service import SubscriptionService
from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionResponse]:
    """The caller's currently-usable subscriptions.

    Includes cancelled-but-not-yet-expired subscriptions — they stay usable
    until the paid period ends.
    """
    return await SubscriptionService(db).list_active(account_id)
