import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.user_management.services.security import (
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_LENGTH,
    password_strength_errors,
)

# E.164: a leading +, a non-zero country digit, then 7-14 more digits.
PHONE_PATTERN = r"^\+[1-9]\d{7,14}$"

PhoneField = Field(..., pattern=PHONE_PATTERN, examples=["+919876543210"])
# Upper bound is bcrypt's 72-byte truncation point, not an arbitrary limit.
PasswordField = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)


def _check_password_strength(password: str) -> str:
    """Shared by every schema that SETS a password (register, change) — never login."""
    errors = password_strength_errors(password)
    if errors:
        raise ValueError("Password must contain " + ", ".join(errors))
    return password


class RegisterRequest(BaseModel):
    phone: str = PhoneField
    display_name: str = Field(..., min_length=1, max_length=100)
    password: str = PasswordField

    _validate_password_strength = field_validator("password")(_check_password_strength)


class LoginRequest(BaseModel):
    """Credentials for one login mode.

    Deliberately a single flat model, NOT a discriminated union keyed on
    `mode`, even though that's the more obvious shape for "credentials for
    one of several modes": the Android client's JSON serializer
    (kotlinx.serialization, `encodeDefaults=false`) omits `mode` from the
    wire entirely when it equals "password" — the client's own default. A
    discriminated union requires the discriminator key to be present to
    resolve which member to validate against, which would reject every
    existing password login. See docs/auth_flow.md.

    `phone`+`password` are required for `mode="password"`; `firebase_id_token`
    is required for `mode="otp"` — enforced below, not via field-level
    `...` (required), since each is genuinely optional depending on the
    other's value.
    """

    mode: Literal["password", "otp"] = "password"
    phone: str | None = Field(None, pattern=PHONE_PATTERN, examples=["+919876543210"])
    # No length/complexity constraints on login: rules are enforced at
    # registration, and applying them here would reject a valid legacy
    # password after a policy change, or leak the policy to an attacker.
    password: str | None = None
    firebase_id_token: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "LoginRequest":
        if self.mode == "password":
            if not self.phone or not self.password:
                raise ValueError("phone and password are required for mode=password")
        elif self.mode == "otp" and not self.firebase_id_token:
            raise ValueError("firebase_id_token is required for mode=otp")
        return self


class LookupRequest(BaseModel):
    """Resolve a phone number to an account.

    POST rather than GET with a query string: a phone number is personal data
    and a query string lands in access logs, proxy logs and browser history.
    """

    phone: str = PhoneField


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = PasswordField

    _validate_password_strength = field_validator("new_password")(_check_password_strength)


class ForgotPasswordRequest(BaseModel):
    """Reset a forgotten password via a Firebase-verified phone number.

    No `current_password` field — proof of phone ownership (the Firebase
    token) is the alternate factor here, standing in for it. See
    AuthService.reset_password / docs/auth_flow.md.
    """

    firebase_id_token: str = Field(..., min_length=1)
    new_password: str = PasswordField

    _validate_password_strength = field_validator("new_password")(_check_password_strength)


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
