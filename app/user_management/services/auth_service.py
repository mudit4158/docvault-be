"""Registration, login and credential management.

See app/user_management/docs/auth_flow.md for the full flow spec.

Pattern every service in this module follows:
  - takes an AsyncSession in __init__, holds it as self.db
  - returns Pydantic response schemas, never ORM objects
  - raises typed exceptions from app.shared.exceptions
  - NEVER calls db.commit() — `get_db` owns the transaction
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.shared.auth.jwt import create_access_token
from app.shared.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.user_management.models.account import Account
from app.user_management.models.auth_identity import AuthIdentity
from app.user_management.models.quota import UploadQuota
from app.user_management.schemas.account import (
    AccountResponse,
    AccountSummary,
    ChangePasswordRequest,
    LoginRequest,
    QuotaResponse,
    RegisterRequest,
    TokenResponse,
)
from app.user_management.services.providers import get_provider
from app.user_management.services.security import hash_password, verify_password


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, data: RegisterRequest) -> AccountResponse:
        """Create an account with a password identity and a quota row.

        All three inserts share one transaction — an Account without an
        UploadQuota would fail the first time that user tried to upload, so
        partial success is not an acceptable outcome.
        """
        existing = await self.db.scalar(select(Account).where(Account.phone == data.phone))
        if existing is not None:
            raise ConflictError("An account with this phone number already exists")

        account = Account(phone=data.phone, display_name=data.display_name)
        self.db.add(account)
        await self.db.flush()  # assigns account.id for the rows below

        self.db.add(
            AuthIdentity(
                account_id=account.id,
                provider="password",
                provider_subject=data.phone,
                secret_hash=hash_password(data.password),
                # The password itself proves nothing about the phone number;
                # verified_at stays null until OTP verification lands (phase 2).
                verified_at=None,
            )
        )
        self.db.add(
            UploadQuota(
                account_id=account.id,
                files_used_today=0,
                period_reset_at=datetime.now(UTC),
                cap_files=settings.daily_upload_cap,
            )
        )
        await self.db.flush()

        return AccountResponse.model_validate(account)

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate via the requested mode and issue an access token."""
        provider = get_provider(data.mode)
        account_id = await provider.authenticate(
            self.db, {"phone": data.phone, "password": data.password}
        )
        return TokenResponse(access_token=create_access_token(str(account_id)))

    async def get_account(self, account_id: uuid.UUID) -> AccountResponse:
        account = await self._require_account(account_id)
        return AccountResponse.model_validate(account)

    async def change_password(
        self, account_id: uuid.UUID, data: ChangePasswordRequest
    ) -> None:
        identity = await self.db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.account_id == account_id,
                AuthIdentity.provider == "password",
            )
        )
        if identity is None or identity.secret_hash is None:
            raise NotFoundError("This account has no password login configured")

        if not verify_password(data.current_password, identity.secret_hash):
            raise UnauthorizedError("Current password is incorrect")

        identity.secret_hash = hash_password(data.new_password)
        await self.db.flush()

    async def lookup_by_phone(self, phone: str) -> AccountSummary:
        """Resolve a phone number to an account, for the invite flow.

        Lets the client show *who* it is about to invite instead of sending a
        bare number into the void, and stops an admin inviting a typo.

        ⚠️ PRIVACY: this confirms whether a number is registered, so it is a
        user-enumeration surface. It does not create a new leak — POST
        /groups/{id}/invite already 404s on unregistered numbers — but it makes
        bulk enumeration much cheaper, since it has no side effects. Mitigated
        by requiring authentication and returning the minimum useful fields.
        NOT yet rate-limited; see docs/auth_flow.md.
        """
        account = await self.db.scalar(select(Account).where(Account.phone == phone))
        if account is None:
            raise NotFoundError(
                f"{phone} does not have an active DocVault account. "
                "Ask them to sign up first, then invite them again."
            )
        return AccountSummary.model_validate(account)

    async def get_quota(self, account_id: uuid.UUID) -> QuotaResponse:
        quota = await self.db.get(UploadQuota, account_id)
        if quota is None:
            raise NotFoundError("Quota not found for this account")
        return QuotaResponse.model_validate(quota)

    async def _require_account(self, account_id: uuid.UUID) -> Account:
        account = await self.db.get(Account, account_id)
        if account is None:
            raise NotFoundError("Account not found")
        return account
