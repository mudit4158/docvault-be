from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.config import settings


def create_access_token(subject: str) -> str:
    """Create a signed JWT with the account UUID as the subject."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> str:
    """Decode and verify a JWT. Returns the subject (account UUID string).

    Raises ValueError on invalid or expired tokens.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        sub: str | None = payload.get("sub")
        if sub is None:
            raise ValueError("Token missing subject")
        return sub
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
