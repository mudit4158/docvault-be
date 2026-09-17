"""Sharing with groups, revocation, cascades, group documents, downloads."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.access_log import AccessLog
from tests.document_management.conftest import DOCS, pdf_bytes, share, upload_ok
from tests.user_management.conftest import User


async def events_for(db: AsyncSession, doc_id: str) -> list[str]:
    return list(
        (
            await db.scalars(
                select(AccessLog.event_type).where(AccessLog.document_id == uuid.UUID(doc_id))
            )
        ).all()
    )


# --- granting -------------------------------------------------------------


async def test_share_with_my_group_gives_members_access(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    grant = await share(client, owner, doc["id"], family, "view")

    assert grant["group_name"] == "Sharma Family"
    assert grant["permission"] == "view"
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 200


async def test_resharing_updates_the_permission_in_place(
    client: AsyncClient, owner: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    first = await share(client, owner, doc["id"], family, "view")
    second = await share(client, owner, doc["id"], family, "download")

    assert second["id"] == first["id"]
    shares = (await client.get(f"{DOCS}/{doc['id']}/shares", headers=owner.auth)).json()
    assert [s["permission"] for s in shares] == ["download"]


async def test_cannot_share_into_a_group_i_am_not_in(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    other = await client.post("/api/v1/groups", json={"name": "Strangers"}, headers=outsider.auth)
    doc = await upload_ok(client, owner)

    resp = await client.post(
        f"{DOCS}/{doc['id']}/shares",
        json={"group_id": other.json()["id"], "permission": "view"},
        headers=owner.auth,
    )
    assert resp.status_code == 404


async def test_member_cannot_reshare(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")

    resp = await client.post(
        f"{DOCS}/{doc['id']}/shares",
        json={"group_id": family, "permission": "download"},
        headers=member.auth,
    )
    assert resp.status_code == 403


async def test_outsider_cannot_list_shares(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.get(f"{DOCS}/{doc['id']}/shares", headers=outsider.auth)
    assert resp.status_code == 404


# --- revoking -------------------------------------------------------------


async def test_revoke_removes_access_and_is_logged(
    client: AsyncClient, owner: User, member: User, family: str, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)
    grant = await share(client, owner, doc["id"], family)

    resp = await client.delete(f"{DOCS}/{doc['id']}/shares/{grant['id']}", headers=owner.auth)
    assert resp.status_code == 204
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 404
    assert "revoke" in await events_for(db, doc["id"])


async def test_can_share_again_after_revoking(
    client: AsyncClient, owner: User, family: str
) -> None:
    """Revoked grants are kept as history; they must not block a new share."""
    doc = await upload_ok(client, owner)
    grant = await share(client, owner, doc["id"], family)
    await client.delete(f"{DOCS}/{doc['id']}/shares/{grant['id']}", headers=owner.auth)

    again = await share(client, owner, doc["id"], family)
    assert again["id"] != grant["id"]


async def test_revoking_an_unknown_share_is_404(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.delete(f"{DOCS}/{doc['id']}/shares/{uuid.uuid4()}", headers=owner.auth)
    assert resp.status_code == 404


async def test_removed_member_loses_access(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    """No grant changes: access resolves through membership at query time."""
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family)

    await client.delete(f"/api/v1/groups/{family}/members/{member.id}", headers=owner.auth)
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).status_code == 404


async def test_deleting_a_group_revokes_shares_but_keeps_the_document(
    client: AsyncClient, owner: User, family: str, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family)

    assert (await client.delete(f"/api/v1/groups/{family}", headers=owner.auth)).status_code == 204

    assert (await client.get(f"{DOCS}/{doc['id']}", headers=owner.auth)).status_code == 200
    assert (await client.get(f"{DOCS}/{doc['id']}/shares", headers=owner.auth)).json() == []
    assert "revoke" in await events_for(db, doc["id"])


# --- group documents tab --------------------------------------------------


async def test_group_documents_lists_what_is_shared(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner, name="Aadhaar")
    await share(client, owner, doc["id"], family, "view")

    items = (
        await client.get(f"/api/v1/groups/{family}/documents", headers=member.auth)
    ).json()
    assert len(items) == 1
    assert items[0]["name"] == "Aadhaar.pdf"
    assert items[0]["owner"]["display_name"] == "Mudit"
    assert items[0]["permission"] == "view"


async def test_group_documents_excludes_revoked_and_trashed(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    revoked = await upload_ok(client, owner, name="Revoked")
    trashed = await upload_ok(client, owner, name="Trashed")
    grant = await share(client, owner, revoked["id"], family)
    await share(client, owner, trashed["id"], family)

    await client.delete(f"{DOCS}/{revoked['id']}/shares/{grant['id']}", headers=owner.auth)
    await client.delete(f"{DOCS}/{trashed['id']}", headers=owner.auth)

    items = (
        await client.get(f"/api/v1/groups/{family}/documents", headers=member.auth)
    ).json()
    assert items == []


async def test_group_documents_hidden_from_non_members(
    client: AsyncClient, family: str, outsider: User
) -> None:
    resp = await client.get(f"/api/v1/groups/{family}/documents", headers=outsider.auth)
    assert resp.status_code == 404


# --- downloading ----------------------------------------------------------


async def test_view_only_member_cannot_download(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "view")

    resp = await client.get(f"{DOCS}/{doc['id']}/download", headers=member.auth)
    assert resp.status_code == 403
    assert "download" in resp.json()["detail"]


async def test_download_permission_returns_the_original_bytes(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    content = pdf_bytes(pages=3)
    doc = await upload_ok(client, owner, content=content, name="Health policy")
    await share(client, owner, doc["id"], family, "download")

    resp = await client.get(f"{DOCS}/{doc['id']}/download", headers=member.auth)
    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"] == "application/pdf"
    assert "Health%20policy.pdf" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"


async def test_download_is_logged(client: AsyncClient, owner: User, db: AsyncSession) -> None:
    doc = await upload_ok(client, owner)
    await client.get(f"{DOCS}/{doc['id']}/download", headers=owner.auth)
    assert "download" in await events_for(db, doc["id"])


async def test_refused_download_is_not_logged(
    client: AsyncClient, owner: User, member: User, family: str, db: AsyncSession
) -> None:
    """A refused attempt is not an access."""
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "view")
    await client.get(f"{DOCS}/{doc['id']}/download", headers=member.auth)

    assert "download" not in await events_for(db, doc["id"])


# --- previewing (in-app view) ----------------------------------------------


async def test_view_only_member_can_preview(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    """The whole point of the view tier: look without downloading."""
    content = pdf_bytes(pages=1)
    doc = await upload_ok(client, owner, content=content)
    await share(client, owner, doc["id"], family, "view")

    resp = await client.get(f"{DOCS}/{doc['id']}/preview", headers=member.auth)
    assert resp.status_code == 200
    assert resp.content == content
    assert "content-disposition" not in resp.headers
    assert resp.headers["cache-control"] == "no-store"


async def test_download_permission_can_also_preview(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")

    resp = await client.get(f"{DOCS}/{doc['id']}/preview", headers=member.auth)
    assert resp.status_code == 200


async def test_non_member_cannot_preview(client: AsyncClient, owner: User, outsider: User) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.get(f"{DOCS}/{doc['id']}/preview", headers=outsider.auth)
    assert resp.status_code == 404


async def test_preview_is_logged_as_view_not_download(
    client: AsyncClient, owner: User, db: AsyncSession
) -> None:
    doc = await upload_ok(client, owner)
    await client.get(f"{DOCS}/{doc['id']}/preview", headers=owner.auth)

    events = await events_for(db, doc["id"])
    assert "view" in events
    assert "download" not in events
