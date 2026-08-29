"""Smoke test — proves the app boots and the test harness wires up correctly.

Feature tests go in tests/<module>/ as each feature lands.
"""

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_documents_requires_auth(client: AsyncClient) -> None:
    """Authenticated routes reject a caller with no bearer token."""
    response = await client.get("/api/v1/documents")
    assert response.status_code == 401
