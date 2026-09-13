"""Soft delete, trash, restore and permanent purge."""

import uuid
from datetime import timedelta
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.access_log import AccessLog
from app.document_management.models.document import Document
from app.document_management.services.document_service import DocumentService
from app.shared.clock import utcnow
from tests.document_management.conftest import DOCS, share, upload_ok
from tests.user_management.conftest import User

TRASH = f"{DOCS}/trash"


async def backdate_deletion(db: AsyncSession, doc_id: str, days: int) -> Document:
    document = await db.get(Document, uuid.UUID(doc_id))
    assert document is not None
    document.deleted_at = utcnow() - timedelta(days=days)
    await db.flush()
    return document


async def test_delete_moves_the_document_to_trash(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)

    assert (await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)).status_code == 204

    trash = (await client.get(TRASH, headers=owner.auth)).json()
    assert [item["id"] for item in trash] == [doc["id"]]
    assert trash[0]["restorable"] is True


async def test_restore_brings_the_document_back(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)

    resp = await client.post(f"{DOCS}/{doc['id']}/restore", headers=owner.auth)
    assert resp.status_code == 200
    assert (await client.get(TRASH, headers=owner.auth)).json() == []
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=owner.auth)).status_code == 200


async def test_delete_revokes_shares_and_restore_does_not_bring_them_back(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    """Decision D2: re-opening access after a restore must be deliberate."""
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family)

    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 404

    await client.post(f"{DOCS}/{doc['id']}/restore", headers=owner.auth)
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 404
    assert (await client.get(f"{DOCS}/{doc['id']}/shares", headers=owner.auth)).json() == []


async def test_restore_after_the_retention_window_is_gone(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    await backdate_deletion(db, doc["id"], days=11)

    resp = await client.post(f"{DOCS}/{doc['id']}/restore", headers=owner.auth)
    assert resp.status_code == 410


async def test_purge_removes_the_file_but_keeps_the_record_and_log(
    client: AsyncClient, owner: User, db: AsyncSession, storage_root: Path
) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    document = await backdate_deletion(db, doc["id"], days=11)
    stored_file = storage_root / str(document.storage_key)
    assert stored_file.exists()

    assert await DocumentService(db).purge_expired() == 1

    assert not stored_file.exists()
    assert document.storage_key is None
    log_count = await db.scalar(
        select(func.count()).select_from(AccessLog).where(AccessLog.document_id == document.id)
    )
    assert log_count == 2  # upload + delete, both kept
    assert (await client.get(TRASH, headers=owner.auth)).json() == []
    assert (await client.post(f"{DOCS}/{doc['id']}/restore", headers=owner.auth)).status_code == 410


async def test_purge_leaves_recent_trash_alone(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)

    assert await DocumentService(db).purge_expired() == 0


async def test_member_cannot_delete(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")
    assert (await client.delete(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 403


async def test_trashed_document_cannot_be_downloaded(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    assert (await client.get(f"{DOCS}/{doc['id']}/download", headers=owner.auth)).status_code == 404


async def test_only_the_owner_can_restore(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    resp = await client.post(f"{DOCS}/{doc['id']}/restore", headers=outsider.auth)
    assert resp.status_code == 404


async def test_restoring_an_active_document_is_404(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    assert (await client.post(f"{DOCS}/{doc['id']}/restore", headers=owner.auth)).status_code == 404
