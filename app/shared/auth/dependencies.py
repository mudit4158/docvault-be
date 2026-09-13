import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.shared.audit.context import set_actor
from app.shared.auth.jwt import decode_token
from app.shared.exceptions import UnauthorizedError

# auto_error=False so a missing header raises our own 401 with a consistent
# body, rather than FastAPI's default shape.
_bearer = HTTPBearer(auto_error=False)


async def get_current_account_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID:
    """Validate the bearer token and return the caller's account id.

    Also stamps the audit actor for this request, so every row the request
    writes is attributed without any service having to pass the id down.

    Add to every authenticated route:
        account_id: uuid.UUID = Depends(get_current_account_id)

    Do NOT add to /auth/register or /auth/login — there is no caller yet.
    """
    if credentials is None:
        raise UnauthorizedError("Not authenticated")

    try:
        account_id = uuid.UUID(decode_token(credentials.credentials))
    except (ValueError, AttributeError):
        raise UnauthorizedError("Invalid or expired token")

    set_actor(account_id)
    return account_id
