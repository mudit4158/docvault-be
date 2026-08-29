# Auth Flow — Implementation Detail

## Overview

DocVault uses **phone number + PIN** authentication. There is no email/password or OAuth for the MVP. The PIN is a short numeric code set at registration.

## Registration Flow (to implement)

```
Client                          Server
  │── POST /auth/register ──────▶│
  │   { phone, pin }              │  1. Validate phone format
  │                               │  2. Check phone not already registered → ConflictError if taken
  │                               │  3. Hash PIN with bcrypt (cost factor 12)
  │                               │  4. INSERT Account(phone, pin_hash)
  │                               │  5. INSERT UploadQuota(account_id, cap_files=settings.daily_upload_cap)
  │                               │     — in the same transaction
  │◀── 201 { account_id } ───────│
```

**Critical:** `Account` and `UploadQuota` must be created in a single transaction. If quota creation fails, the account must not be committed.

## Login Flow (implemented in `auth_service.py`)

```
Client                          Server
  │── POST /auth/login ──────────▶│
  │   { phone, pin }              │  1. SELECT Account WHERE phone = ?
  │                               │  2. If not found → NotFoundError (do not leak "wrong PIN")
  │                               │  3. bcrypt.verify(pin, account.pin_hash)
  │                               │  4. If mismatch → ForbiddenError
  │                               │  5. create_access_token(str(account.id))
  │◀── 200 { access_token } ─────│
```

**Security note:** Return the same error for "account not found" and "wrong PIN" in production to avoid user enumeration. For the MVP we return distinct errors for simplicity.

## PIN Hashing

Use `passlib` with bcrypt:

```python
from passlib.context import CryptContext

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_pin(plain: str) -> str:
    return _ctx.hash(plain)

def verify_pin(plain: str, hashed: str) -> bool:
    return _ctx.verify(plain, hashed)
```

Store only the hash in `Account.pin_hash`. Never log or return the plain PIN.

## Token Lifecycle

- Tokens are signed JWTs (HS256). The `sub` claim holds the account UUID string.
- Expiry is controlled by `settings.access_token_expire_minutes` (default 60 min).
- There is no refresh token in MVP. The client re-authenticates after expiry.
- Token revocation is not implemented in MVP (stateless).

## Future: Biometric Auth (Mobile)

The mobile app uses biometric unlock as the primary method, with PIN as fallback (screen 01). Biometric auth happens **client-side** — the device verifies the biometric and then sends the stored PIN to this endpoint. The server never handles biometric data.

## PIN Change Flow (to implement)

```
PATCH /me/pin
{ current_pin, new_pin }

1. Verify current_pin against account.pin_hash
2. Hash new_pin
3. UPDATE Account SET pin_hash = ?
```

## App Lock (Mobile only, no backend involvement)

The "app lock" screen (screen 01) is purely client-side state. The server has no concept of a "locked" session.
