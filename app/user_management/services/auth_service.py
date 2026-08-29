"""Auth service — the SAMPLE FLOW for user_management.

This is the reference implementation every other service in this module should
follow. See `app/user_management/docs/auth_flow.md` for the full flow spec.

Pattern to copy:
  - Service takes an AsyncSession in __init__ and holds it as self.db
  - Every public method is async and returns a Pydantic response schema
  - Business rule violations raise typed exceptions from app.shared.exceptions
  - The service NEVER calls db.commit() — `get_db` handles that
"""

import uuid

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.jwt import create_access_token
from app.shared.exceptions import ForbiddenError, NotFoundError
from app.user_management.models.account import Account
from app.user_management.schemas.account import AccountResponse, TokenResponse

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_pin(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_pin(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def login(self, phone: str, pin: str) -> TokenResponse:
        """Phone + PIN login. Returns a signed bearer token.

        Steps (mirrors docs/auth_flow.md):
          1. Look up the account by phone.
          2. Verify the PIN against the stored bcrypt hash.
          3. Issue a JWT with the account UUID as subject.
        """
        result = await self.db.execute(select(Account).where(Account.phone == phone))
        account = result.scalar_one_or_none()

        if account is None:
            raise NotFoundError("No account found for this phone number")

        if not verify_pin(pin, account.pin_hash):
            raise ForbiddenError("Incorrect PIN")

        return TokenResponse(access_token=create_access_token(str(account.id)))

    async def get_account(self, account_id: uuid.UUID) -> AccountResponse:
        """Fetch the authenticated account's profile."""
        result = await self.db.execute(select(Account).where(Account.id == account_id))
        account = result.scalar_one_or_none()

        if account is None:
            raise NotFoundError("Account not found")

        return AccountResponse.model_validate(account)
