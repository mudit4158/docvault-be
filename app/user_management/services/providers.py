"""Multi-mode authentication providers.

Login is dispatched on a `mode` field to one provider per authentication
method. Each provider's only job is to turn credentials into an account id;
everything downstream — token issuance, audit, the auth dependency — is
mode-agnostic and never changes when a mode is added.

Adding OTP or Google later is a new subclass plus one registry entry. No route
changes, no token changes, no migration: `AuthIdentity` already carries the
provider enum.

See docs/auth_flow.md.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exceptions import UnauthorizedError
from app.user_management.models.auth_identity import AuthIdentity
from app.user_management.services.security import hash_password, verify_password


class AuthProvider(ABC):
    """Turns a set of credentials into an authenticated account id."""

    provider_key: str

    @abstractmethod
    async def authenticate(self, db: AsyncSession, credentials: dict[str, Any]) -> uuid.UUID:
        """Return the account id, or raise UnauthorizedError.

        Implementations MUST raise the same error for "no such identity" and
        "wrong secret" — see PasswordProvider for why.
        """


class PasswordProvider(AuthProvider):
    """Phone number + password."""

    provider_key = "password"

    async def authenticate(self, db: AsyncSession, credentials: dict[str, Any]) -> uuid.UUID:
        phone: str = credentials["phone"]
        password: str = credentials["password"]

        result = await db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == self.provider_key,
                AuthIdentity.provider_subject == phone,
            )
        )
        identity = result.scalar_one_or_none()

        # Deliberately identical failures for "no such account" and "wrong
        # password". Distinguishing them lets anyone enumerate which phone
        # numbers are registered, which for a vault holding identity documents
        # is itself a disclosure. The cost is a slightly less helpful error.
        if identity is None or identity.secret_hash is None:
            # Still hash something so the response time does not reveal whether
            # the account exists.
            verify_password(password, _DUMMY_HASH)
            raise UnauthorizedError("Invalid phone number or password")

        if not verify_password(password, identity.secret_hash):
            raise UnauthorizedError("Invalid phone number or password")

        identity.last_used_at = datetime.now(UTC)
        return identity.account_id


# Computed once at import so the "no such account" path costs the same bcrypt
# work as a real verification, rather than returning noticeably faster and
# revealing that the phone number is unregistered.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder")


_PROVIDERS: dict[str, AuthProvider] = {
    PasswordProvider.provider_key: PasswordProvider(),
    # "otp":    OtpProvider(),      -> phase 2
    # "google": GoogleProvider(),   -> phase 3
}


def get_provider(mode: str) -> AuthProvider:
    provider = _PROVIDERS.get(mode)
    if provider is None:
        raise UnauthorizedError(f"Unsupported login mode: {mode}")
    return provider
