import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.shared.auth.jwt import decode_token

_bearer = HTTPBearer()


async def get_current_account_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> uuid.UUID:
    """FastAPI dependency — validates the bearer token and returns the caller's account UUID.

    Usage in any authenticated route:
        account_id: uuid.UUID = Depends(get_current_account_id)

    Do NOT add this to auth routes (login, register).
    """
    try:
        raw = decode_token(credentials.credentials)
        return uuid.UUID(raw)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
