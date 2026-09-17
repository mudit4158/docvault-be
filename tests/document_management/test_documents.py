"""Listing, searching, detail, rename and type change."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.access_log import AccessLog
from tests.document_management.conftest import DOCS, share, upload_ok
from tests.user_management.conftest import User


async def names(client: AsyncClient, user: User, query: str = "") -> list[str]:
    resp = await client.get(f"{DOCS}{query}", headers=user.auth)
    assert resp.status_code == 200, resp.text
    return sorted(item["name"] for item in resp.json()["items"])


async def tag(client: AsyncClient, user: User, doc_id: str, label: str) -> None:
    resp = await client.post(f"{DOCS}/{doc_id}/tags", json={"label": label}, headers=user.auth)
    assert resp.status_code == 200, resp.text


# --- listing --------------------------------------------------------------


async def test_list_shows_only_my_documents(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    await upload_ok(client, owner, name="Mine")
    await upload_ok(client, outsider, name="Theirs")

    assert await names(client, owner) == ["Mine.pdf"]


async def test_list_includes_tags_and_share_count(
    client: AsyncClient, owner: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await tag(client, owner, doc["id"], "Identity Proof")
    await share(client, owner, doc["id"], family)

    item = (await client.get(DOCS, headers=owner.auth)).json()["items"][0]
    assert [t["label"] for t in item["tags"]] == ["Identity Proof"]
    assert item["share_count"] == 1


async def test_search_matches_the_name(client: AsyncClient, owner: User) -> None:
    await upload_ok(client, owner, name="Aadhaar")
    await upload_ok(client, owner, name="PAN card")

    assert await names(client, owner, "?q=pan") == ["PAN card.pdf"]


async def test_search_matches_tag_labels(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner, name="Discharge summary")
    await upload_ok(client, owner, name="Electricity bill")
    await tag(client, owner, doc["id"], "Medical")

    assert await names(client, owner, "?q=medic") == ["Discharge summary.pdf"]


async def test_search_wildcards_are_literal(client: AsyncClient, owner: User) -> None:
    await upload_ok(client, owner, name="Aadhaar")
    assert await names(client, owner, "?q=%25") == []


async def test_filter_by_document_type(client: AsyncClient, owner: User) -> None:
    await upload_ok(client, owner, name="Card", doc_type="pan")
    await upload_ok(client, owner, name="Passport", doc_type="passport")

    assert await names(client, owner, "?doc_type=passport") == ["Passport.pdf"]


async def test_filter_by_tag(client: AsyncClient, owner: User) -> None:
    home = await upload_ok(client, owner, name="Sale deed")
    await upload_ok(client, owner, name="Aadhaar")
    await tag(client, owner, home["id"], "Home")

    assert await names(client, owner, "?tag=home") == ["Sale deed.pdf"]


async def test_trashed_documents_are_not_listed(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    await client.delete(f"{DOCS}/{doc['id']}", headers=owner.auth)
    assert await names(client, owner) == []


# --- detail ---------------------------------------------------------------


async def test_owner_detail_includes_shares_and_tags(
    client: AsyncClient, owner: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await tag(client, owner, doc["id"], "Favourites")
    await share(client, owner, doc["id"], family, "download")

    detail = (await client.get(f"{DOCS}/{doc['id']}", headers=owner.auth)).json()
    assert detail["my_permission"] == "owner"
    assert [s["group_name"] for s in detail["shares"]] == ["Sharma Family"]
    assert [t["label"] for t in detail["tags"]] == ["Favourites"]


async def test_member_detail_hides_owner_only_information(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    """A member must not learn the owner's private labels or other shares."""
    doc = await upload_ok(client, owner)
    await tag(client, owner, doc["id"], "Medical")
    await share(client, owner, doc["id"], family, "view")

    detail = (await client.get(f"{DOCS}/{doc['id']}", headers=member.auth)).json()
    assert detail["my_permission"] == "view"
    assert detail["owner"]["display_name"] == "Mudit"
    assert detail["shares"] is None
    assert detail["tags"] == []


async def test_outsider_gets_404_not_403(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    doc = await upload_ok(client, owner)
    assert (await client.get(f"{DOCS}/{doc['id']}", headers=outsider.auth)).status_code == 404


async def test_unknown_document_is_404(client: AsyncClient, owner: User) -> None:
    assert (await client.get(f"{DOCS}/{uuid.uuid4()}", headers=owner.auth)).status_code == 404


# --- rename and type --------------------------------------------------------


async def test_rename_keeps_the_extension(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.patch(
        f"{DOCS}/{doc['id']}", json={"name": "My Aadhaar.exe"}, headers=owner.auth
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Aadhaar.pdf"


async def test_rename_is_logged(client: AsyncClient, owner: User, db: AsyncSession) -> None:
    doc = await upload_ok(client, owner)
    await client.patch(f"{DOCS}/{doc['id']}", json={"name": "Renamed"}, headers=owner.auth)

    events = (
        await db.scalars(
            select(AccessLog.event_type).where(AccessLog.document_id == uuid.UUID(doc["id"]))
        )
    ).all()
    assert sorted(events) == ["rename", "upload"]


async def test_rename_rejects_path_separators(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.patch(
        f"{DOCS}/{doc['id']}", json={"name": "../../etc/passwd"}, headers=owner.auth
    )
    assert resp.status_code == 422


async def test_change_document_type(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner, doc_type="other")
    resp = await client.patch(f"{DOCS}/{doc['id']}", json={"doc_type": "pan"}, headers=owner.auth)
    assert resp.json()["doc_type"] == "pan"


async def test_member_cannot_rename(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")

    resp = await client.patch(
        f"{DOCS}/{doc['id']}", json={"name": "Hijacked"}, headers=member.auth
    )
    assert resp.status_code == 403
