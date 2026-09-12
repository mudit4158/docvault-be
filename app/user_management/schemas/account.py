import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.user_management.services.security import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH

# E.164: a leading +, a non-zero country digit, then 7-14 more digits.
PHONE_PATTERN = r"^\+[1-9]\d{7,14}$"

PhoneField = Field(..., pattern=PHONE_PATTERN, examples=["+919876543210"])
# Upper bound is bcrypt's 72-byte truncation point, not an arbitrary limit.
PasswordField = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)


class RegisterRequest(BaseModel):
    phone: str = PhoneField
    display_name: str = Field(..., min_length=1, max_length=100)
    password: str = PasswordField


class LoginRequest(BaseModel):
    """Credentials for one login mode.

    `mode` selects the provider. Only "password" is implemented; when OTP and
    SSO land this becomes a discriminated union over per-mode request models
    (see docs/auth_flow.md) — the field exists now so clients send it from day
    one and nothing has to change on their side later.
    """

    mode: Literal["password"] = "password"
    phone: str = PhoneField
    # No length constraints on login: rules are enforced at registration, and
    # applying them here would reject a valid legacy password after a policy
    # change, or leak the policy to an attacker.
    password: str


class LookupRequest(BaseModel):
    """Resolve a phone number to an account.

    POST rather than GET with a query string: a phone number is personal data
    and a query string lands in access logs, proxy logs and browser history.
    """

    phone: str = PhoneField


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = PasswordField


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountResponse(BaseModel):
    id: uuid.UUID
    phone: str
    display_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountSummary(BaseModel):
    """A person as they appear inside someone else's context — a group member
    row, an invitation's sender. Deliberately omits `created_at`.
    """

    id: uuid.UUID
    phone: str
    display_name: str

    model_config = {"from_attributes": True}


class QuotaResponse(BaseModel):
    files_used_today: int
    cap_files: int
    period_reset_at: datetime

    model_config = {"from_attributes": True}
