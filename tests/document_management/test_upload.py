"""Uploading documents: validation order, quota, encryption, logging."""

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.document_management.models.access_log import AccessLog
from app.document_management.models.document import Document
from app.shared.clock import utcnow
from app.user_management.models.quota import UploadQuota
from tests.audit_helpers import audit_rows
from tests.document_management.conftest import PNG_BYTES, pdf_bytes, upload, upload_ok
from tests.user_management.conftest import User

QUOTA = "/api/v1/auth/me/quota"


async def used_today(client: AsyncClient, user: User) -> int:
    return (await client.get(QUOTA, headers=user.auth)).json()["files_used_today"]


# --- happy path -----------------------------------------------------------


async def test_upload_returns_the_document(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner, content=pdf_bytes(pages=2))

    assert doc["name"] == "Aadhaar.pdf"
    assert doc["doc_type"] == "aadhaar"
    assert doc["mime_type"] == "application/pdf"
    assert doc["page_count"] == 2
    assert doc["size_bytes"] > 0
    assert doc["tags"] == []
    assert doc["share_count"] == 0


async def test_file_is_encrypted_at_rest(
    client: AsyncClient, owner: User, db: AsyncSession, storage_root: Path
) -> None:
    content = pdf_bytes()
    doc = await upload_ok(client, owner, content=content)

    document = await db.get(Document, uuid.UUID(doc["id"]))
    assert document is not None and document.storage_key is not None
    on_disk = (storage_root / document.storage_key).read_bytes()

    assert not on_disk.startswith(b"%PDF")
    assert content not in on_disk


async def test_upload_consumes_one_unit_of_quota(client: AsyncClient, owner: User) -> None:
    before = await used_today(client, owner)
    await upload_ok(client, owner)
    assert await used_today(client, owner) == before + 1


async def test_image_upload(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(
        client, owner, filename="PAN.png", content=PNG_BYTES, mime="image/png", doc_type="pan"
    )
    assert doc["mime_type"] == "image/png"
    assert doc["page_count"] is None


async def test_custom_name_keeps_the_real_extension(client: AsyncClient, owner: User) -> None:
    """Whatever extension is typed, the stored one comes from the file."""
    doc = await upload_ok(client, owner, name="Passport scan.docx")
    assert doc["name"] == "Passport scan.pdf"


async def test_custom_name_without_extension_gets_one(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner, name="Voter ID")
    assert doc["name"] == "Voter ID.pdf"


async def test_upload_is_logged_and_audited(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)

    logs = (
        await db.scalars(select(AccessLog).where(AccessLog.document_id == uuid.UUID(doc["id"])))
    ).all()
    assert [log.event_type for log in logs] == ["upload"]
    assert str(logs[0].actor_id) == owner.id

    inserts = await audit_rows(db, "documents", operation="INSERT")
    assert len(inserts) == 1
    assert inserts[0]["name"] == "Aadhaar.pdf"


# --- rejections never cost quota ------------------------------------------


async def test_oversized_file_is_rejected_before_quota(
    client: AsyncClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_upload_size_bytes", 512)
    resp = await upload(client, owner, content=pdf_bytes() + b"0" * 1024)

    assert resp.status_code == 413
    assert "limit" in resp.json()["detail"]
    assert await used_today(client, owner) == 0


async def test_unsupported_type_is_rejected_before_quota(
    client: AsyncClient, owner: User
) -> None:
    resp = await upload(
        client, owner, filename="setup.exe", content=b"MZ" + b"\x00" * 64,
        mime="application/octet-stream",
    )
    assert resp.status_code == 415
    assert await used_today(client, owner) == 0


async def test_content_must_match_the_extension(client: AsyncClient, owner: User) -> None:
    resp = await upload(client, owner, content=b"MZ\x90\x00" + b"\x00" * 64)
    assert resp.status_code == 415


async def test_empty_file_is_rejected(client: AsyncClient, owner: User) -> None:
    assert (await upload(client, owner, content=b"")).status_code == 415


async def test_unknown_document_type_is_rejected(client: AsyncClient, owner: User) -> None:
    assert (await upload(client, owner, doc_type="driving_licence")).status_code == 422


async def test_upload_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/documents", files={"file": ("a.pdf", pdf_bytes(), "application/pdf")}
    )
    assert resp.status_code == 401


# --- daily cap ------------------------------------------------------------


async def test_daily_cap_blocks_further_uploads(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    quota = await db.get(UploadQuota, uuid.UUID(owner.id))
    assert quota is not None
    quota.cap_files = 1
    quota.files_used_today = 0
    quota.period_reset_at = utcnow() + timedelta(hours=6)
    await db.flush()

    await upload_ok(client, owner)
    resp = await upload(client, owner)

    assert resp.status_code == 429
    assert "uploads for today" in resp.json()["detail"]


async def test_cap_resets_when_the_window_passes(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    quota = await db.get(UploadQuota, uuid.UUID(owner.id))
    assert quota is not None
    quota.cap_files = 1
    quota.files_used_today = 1
    quota.period_reset_at = utcnow() - timedelta(minutes=1)
    await db.flush()

    await upload_ok(client, owner)
