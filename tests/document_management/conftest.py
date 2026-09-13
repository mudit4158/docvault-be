"""Fixtures and helpers for document_management tests."""

import io
from pathlib import Path

import pytest
from httpx import AsyncClient, Response
from pypdf import PdfWriter

from app.config import settings
from tests.user_management.conftest import User, add_member, make_user

DOCS = "/api/v1/documents"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own empty storage directory."""
    root = tmp_path / "vault"
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_storage_path", str(root))
    return root


def pdf_bytes(pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def upload(
    client: AsyncClient,
    user: User,
    *,
    filename: str = "Aadhaar.pdf",
    content: bytes | None = None,
    doc_type: str = "aadhaar",
    name: str | None = None,
    mime: str = "application/pdf",
) -> Response:
    data = {"doc_type": doc_type}
    if name is not None:
        data["name"] = name
    return await client.post(
        DOCS,
        files={"file": (filename, content if content is not None else pdf_bytes(), mime)},
        data=data,
        headers=user.auth,
    )


async def upload_ok(client: AsyncClient, user: User, **kwargs: object) -> dict:
    resp = await upload(client, user, **kwargs)  # type: ignore[arg-type]
    assert resp.status_code == 201, resp.text
    return resp.json()


async def share(
    client: AsyncClient, owner: User, document_id: str, group_id: str, permission: str = "view"
) -> dict:
    resp = await client.post(
        f"{DOCS}/{document_id}/shares",
        json={"group_id": group_id, "permission": permission},
        headers=owner.auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def owner(client: AsyncClient) -> User:
    return await make_user(client, "+919100000001", "Mudit")


@pytest.fixture
async def member(client: AsyncClient) -> User:
    return await make_user(client, "+919100000002", "Riya")


@pytest.fixture
async def outsider(client: AsyncClient) -> User:
    return await make_user(client, "+919100000003", "Nikhil")


@pytest.fixture
async def family(client: AsyncClient, owner: User, member: User) -> str:
    """A group run by `owner`, with `member` in it."""
    resp = await client.post(
        "/api/v1/groups", json={"name": "Sharma Family"}, headers=owner.auth
    )
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]
    await add_member(client, group_id, owner, member)
    return group_id
