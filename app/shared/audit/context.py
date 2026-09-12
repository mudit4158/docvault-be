"""Actor propagation for the audit framework.

The audit listeners run deep inside a session flush, far from the request that
triggered it, so the acting account id cannot be passed down as an argument.
A ContextVar carries it instead — set once by the auth dependency, read by the
listener.

ContextVar (not a global) because each concurrent request in the event loop
needs its own value; a module-level global would leak one request's actor into
another's audit rows.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current_actor_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_actor_id", default=None
)


def set_actor(account_id: uuid.UUID | None) -> object:
    """Set the acting account for this context. Returns a reset token."""
    return _current_actor_id.set(account_id)


def get_actor() -> uuid.UUID | None:
    """The account performing the current operation, if any.

    None for unauthenticated actions (registration, login attempts) and for
    background jobs. Audit rows with a null actor are expected, not a bug.
    """
    return _current_actor_id.get()


def reset_actor(token: object) -> None:
    _current_actor_id.reset(token)  # type: ignore[arg-type]


@contextmanager
def acting_as(account_id: uuid.UUID | None) -> Iterator[None]:
    """Scope a block of work to an actor. Used by jobs and tests."""
    token = set_actor(account_id)
    try:
        yield
    finally:
        reset_actor(token)
