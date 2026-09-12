import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.user_management.schemas.account import (
    AccountResponse,
    ChangePasswordRequest,
    LoginRequest,
    QuotaResponse,
    RegisterRequest,
    TokenResponse,
)
from app.user_management.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

# /auth/register and /auth/login are the ONLY unauthenticated routes in the
# API — there is no caller to authenticate yet. Every other route in every
# module carries the get_current_account_id dependency.


@router.post("/register", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AccountResponse:
    """Create an account with phone + password."""
    return await AuthService(db).register(body)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Authenticate and receive a bearer token."""
    return await AuthService(db).login(body)


@router.get("/me", response_model=AccountResponse)
async def me(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> AccountResponse:
    """The authenticated account's own profile."""
    return await AuthService(db).get_account(account_id)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change the account's password. Requires the current one."""
    await AuthService(db).change_password(account_id, body)


@router.get("/me/quota", response_model=QuotaResponse)
async def my_quota(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> QuotaResponse:
    """Daily upload allowance and when it resets."""
    return await AuthService(db).get_quota(account_id)
