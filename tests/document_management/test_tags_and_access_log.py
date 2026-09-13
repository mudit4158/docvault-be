"""Tags and the owner-only access log."""

from httpx import AsyncClient

from tests.document_management.conftest import DOCS, share, upload_ok
from tests.user_management.conftest import User


async def add_tag(client: AsyncClient, user: User, doc_id: str, label: str):  # type: ignore[no-untyped-def]
    return await client.post(f"{DOCS}/{doc_id}/tags", json={"label": label}, headers=user.auth)


# --- tags -----------------------------------------------------------------


async def test_add_a_tag(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    resp = await add_tag(client, owner, doc["id"], "Identity Proof")
    assert resp.status_code == 200
    assert [t["label"] for t in resp.json()] == ["Identity Proof"]


async def test_adding_the_same_tag_twice_is_harmless(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    await add_tag(client, owner, doc["id"], "Home")
    resp = await add_tag(client, owner, doc["id"], "Home")
    assert [t["label"] for t in resp.json()] == ["Home"]


async def test_tags_match_case_insensitively_with_whitespace_collapsed(
    client: AsyncClient, owner: User
) -> None:
    doc = await upload_ok(client, owner)
    await add_tag(client, owner, doc["id"], "Identity Proof")
    resp = await add_tag(client, owner, doc["id"], "  identity   PROOF ")
    assert [t["label"] for t in resp.json()] == ["Identity Proof"]


async def test_remove_a_tag(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    added = (await add_tag(client, owner, doc["id"], "Medical")).json()

    resp = await client.delete(f"{DOCS}/{doc['id']}/tags/{added[0]['id']}", headers=owner.auth)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_suggestions_never_include_other_peoples_labels(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    theirs = await upload_ok(client, outsider)
    await add_tag(client, outsider, theirs["id"], "Divorce papers")
    mine = await upload_ok(client, owner)
    await add_tag(client, owner, mine["id"], "Car")

    suggestions = (await client.get("/api/v1/tags", headers=owner.auth)).json()
    assert {"Favourites", "Identity Proof", "Medical", "Home", "Car"} <= set(suggestions)
    assert "Divorce papers" not in suggestions


async def test_member_cannot_tag(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")
    assert (await add_tag(client, member, doc["id"], "Mine now")).status_code == 403


async def test_blank_tag_is_rejected(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    assert (await add_tag(client, owner, doc["id"], "   ")).status_code == 422


async def test_overlong_tag_is_rejected(client: AsyncClient, owner: User) -> None:
    doc = await upload_ok(client, owner)
    assert (await add_tag(client, owner, doc["id"], "x" * 65)).status_code == 422


# --- access log -----------------------------------------------------------


async def test_owner_sees_activity_newest_first(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")
    await client.get(f"{DOCS}/{doc['id']}/download", headers=member.auth)
    await client.get(f"{DOCS}/{doc['id']}/download", headers=owner.auth)

    page = (await client.get(f"{DOCS}/{doc['id']}/access-log", headers=owner.auth)).json()
    assert [e["event_type"] for e in page["items"]] == ["download", "download", "share", "upload"]
    assert [e["actor"]["display_name"] for e in page["items"][:2]] == ["Mudit", "Riya"]
    assert page["total"] == 4
    assert page["download_count"] == 2


async def test_member_cannot_read_the_access_log(
    client: AsyncClient, owner: User, member: User, family: str
) -> None:
    doc = await upload_ok(client, owner)
    await share(client, owner, doc["id"], family, "download")
    resp = await client.get(f"{DOCS}/{doc['id']}/access-log", headers=member.auth)
    assert resp.status_code == 403


async def test_outsider_cannot_read_the_access_log(
    client: AsyncClient, owner: User, outsider: User
) -> None:
    doc = await upload_ok(client, owner)
    resp = await client.get(f"{DOCS}/{doc['id']}/access-log", headers=outsider.auth)
    assert resp.status_code == 404
