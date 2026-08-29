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

# Importing every model module registers its tables on Base.metadata.
# These must come before the `fastapi_app` import below, and must use the
# `import x.y as z` form — a bare `import app.billing.models.subscription`
# binds the name `app` to the PACKAGE, shadowing the FastAPI instance.
import app.billing.models.subscription as _m_subscription  # noqa: F401
import app.document_management.models.access_log as _m_access_log  # noqa: F401
import app.document_management.models.document as _m_document  # noqa: F401
import app.document_management.models.share_grant as _m_share_grant  # noqa: F401
import app.document_management.models.tag as _m_tag  # noqa: F401
import app.user_management.models.account as _m_account  # noqa: F401
import app.user_management.models.group as _m_group  # noqa: F401
import app.user_management.models.quota as _m_quota  # noqa: F401
from app.main import app as fastapi_app
from app.shared.db.base import Base
from app.shared.db.session import get_db


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()
