"""Shared pytest fixtures.

Tests run against an in-memory SQLite database with the real schema created
from `Base.metadata`, so model changes are exercised without needing Postgres
locally. Anything relying on Postgres-specific SQL should be marked and run
against a real database in CI.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Registers every model AND the generated audit tables, so create_all builds
# the complete schema. Aliased import: a bare `import app.registry` would bind
# the name `app` to the PACKAGE, shadowing the FastAPI instance below.
import app.registry as _registry  # noqa: F401
import app.shared.audit as _audit  # noqa: F401  (registers the session listeners)
from app.main import app as fastapi_app
from app.shared.audit.context import set_actor
from app.shared.db.base import Base
from app.shared.db.session import get_db


@pytest.fixture(autouse=True)
def _clear_audit_actor() -> None:
    """Reset the audit actor between tests.

    The ContextVar would otherwise leak one test's actor into the next, making
    audit assertions pass or fail depending on test order.
    """
    set_actor(None)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    # StaticPool keeps every connection pointed at the same in-memory database;
    # without it each connection gets its own empty one.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with the DB dependency overridden to use the test session."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db
        await db.commit()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()
