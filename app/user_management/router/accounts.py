import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.user_management.schemas.account import AccountSummary, LookupRequest
from app.user_management.services.auth_service import AuthService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("/lookup", response_model=AccountSummary)
async def lookup_account(
    body: LookupRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> AccountSummary:
    """Resolve a phone number to a DocVault account.

    Lets the invite flow show *who* is about to be invited rather than sending
    a bare number, and catches a typo before an invitation goes out.

    404 when the number has no account — the message says what to do about it.

    POST, not GET: a phone number is personal data, and a query string ends up
    in access logs, proxy logs and browser history.
    """
    return await AuthService(db).lookup_by_phone(body.phone)
