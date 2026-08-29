import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.user_management.schemas.account import AccountResponse, LoginRequest, TokenResponse
from app.user_management.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Phone + PIN login. Returns a bearer token."""
    return await AuthService(db).login(body.phone, body.pin)


@router.get("/me", response_model=AccountResponse)
async def me(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> AccountResponse:
    """Return the authenticated account's profile."""
    return await AuthService(db).get_account(account_id)
