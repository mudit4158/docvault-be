"""Shared Firebase ID-token verification.

Used by both OTP login (`providers.FirebaseOtpProvider`) and forgot-password
(`AuthService.reset_password`) — both need exactly the same thing: proof of
phone ownership via a Firebase-verified ID token, resolved to an existing
DocVault account. Firebase Phone Auth is entirely client-driven — the app
talks to Firebase directly; this only ever verifies the token afterward. See
docs/auth_flow.md.
"""

from datetime import timedelta

from firebase_admin import auth as firebase_auth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.shared.clock import ensure_utc, utcnow
from app.shared.exceptions import UnauthorizedError
from app.shared.firebase import ensure_firebase_app
from app.user_management.models.account import Account
from app.user_management.models.otp_attempt import OtpAttempt


async def verify_phone_and_resolve_account(db: AsyncSession, id_token: str) -> Account:
    """Verify `id_token`, return the matching Account, or raise UnauthorizedError.

    Failures are NOT uniform the way PasswordProvider's are — a valid
    Firebase token already proves the caller controls that phone number, so
    "no DocVault account for this number" is information they already
    proved they're entitled to, not a credential-guessing leak. What IS
    worth throttling: repeatedly presenting valid tokens for numbers with no
    account, which would otherwise let someone enumerate registered numbers
    one phone they control at a time — see OtpAttempt. A malformed/expired/
    forged token never reaches that throttle at all: there's no phone number
    to attribute it to, and forging a valid-looking Firebase token isn't a
    realistic attack surface this needs to defend against.
    """
    ensure_firebase_app()
    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as exc:
        raise UnauthorizedError("Invalid or expired verification code") from exc

    phone: str | None = decoded.get("phone_number")
    if not phone:
        raise UnauthorizedError("Invalid or expired verification code")

    now = utcnow()
    attempt = await db.get(OtpAttempt, phone)
    if (
        attempt is not None
        and attempt.locked_until is not None
        and ensure_utc(attempt.locked_until) > now
    ):
        raise UnauthorizedError("Too many attempts for this number. Try again later.")

    account = await db.scalar(select(Account).where(Account.phone == phone))
    if account is None:
        if attempt is None:
            attempt = OtpAttempt(phone=phone, failed_count=0)
            db.add(attempt)
        attempt.failed_count += 1
        if attempt.failed_count >= settings.otp_max_verify_attempts:
            attempt.locked_until = now + timedelta(minutes=settings.otp_lockout_minutes)
        # Flushed explicitly: the exception below propagates immediately, and
        # this write must survive regardless of what the caller's
        # transaction boundary does with the exception.
        await db.flush()
        raise UnauthorizedError(f"No DocVault account found for {phone}. Register first.")

    if attempt is not None and (attempt.failed_count or attempt.locked_until):
        attempt.failed_count = 0
        attempt.locked_until = None

    return account
