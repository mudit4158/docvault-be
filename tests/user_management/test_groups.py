"""Group creation, listing, detail, update, delete."""

from httpx import AsyncClient

from tests.user_management.conftest import User, add_member

GROUPS = "/api/v1/groups"


# --- create ---------------------------------------------------------------


async def test_create_group_makes_caller_admin(client: AsyncClient, admin: User) -> None:
    resp = await client.post(
        GROUPS, json={"name": "Flat 402 — Paperwork"}, headers=admin.auth
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Flat 402 — Paperwork"
    assert body["my_role"] == "admin"
    assert body["member_count"] == 1


async def test_create_group_accepts_description(client: AsyncClient, admin: User) -> None:
    resp = await client.post(
        GROUPS, json={"name": "Care Circle", "description": "Amma's papers"},
        headers=admin.auth,
    )
    assert resp.json()["description"] == "Amma's papers"


async def test_create_group_requires_auth(client: AsyncClient) -> None:
    assert (await client.post(GROUPS, json={"name": "X"})).status_code == 401


async def test_create_group_rejects_blank_name(client: AsyncClient, admin: User) -> None:
    resp = await client.post(GROUPS, json={"name": ""}, headers=admin.auth)
    assert resp.status_code == 422


# --- list -----------------------------------------------------------------


async def test_list_returns_only_my_groups(
    client: AsyncClient, admin: User, outsider: User, group: str
) -> None:
    mine = await client.get(GROUPS, headers=admin.auth)
    assert len(mine.json()) == 1

    theirs = await client.get(GROUPS, headers=outsider.auth)
    assert theirs.json() == []


async def test_list_reports_role_and_member_count(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    as_admin = (await client.get(GROUPS, headers=admin.auth)).json()[0]
    assert as_admin["my_role"] == "admin"
    assert as_admin["member_count"] == 2

    as_member = (await client.get(GROUPS, headers=member.auth)).json()[0]
    assert as_member["my_role"] == "member"
    assert as_member["member_count"] == 2


# --- detail ---------------------------------------------------------------


async def test_member_can_read_group_detail(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.get(f"{GROUPS}/{group}", headers=member.auth)
    assert resp.status_code == 200
    assert resp.json()["my_role"] == "member"


async def test_non_member_cannot_read_group_detail(
    client: AsyncClient, outsider: User, group: str
) -> None:
    """404 not 403 — a non-member must not learn the group exists."""
    resp = await client.get(f"{GROUPS}/{group}", headers=outsider.auth)
    assert resp.status_code == 404


async def test_unknown_group_is_404(client: AsyncClient, admin: User) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"{GROUPS}/{unknown}", headers=admin.auth)).status_code == 404


# --- update ---------------------------------------------------------------


async def test_admin_can_rename_group(client: AsyncClient, admin: User, group: str) -> None:
    resp = await client.patch(
        f"{GROUPS}/{group}", json={"name": "Sharma Family Health"}, headers=admin.auth
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Sharma Family Health"


async def test_member_cannot_rename_group(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.patch(
        f"{GROUPS}/{group}", json={"name": "Hijacked"}, headers=member.auth
    )
    assert resp.status_code == 403


# --- delete ---------------------------------------------------------------


async def test_admin_can_delete_group(client: AsyncClient, admin: User, group: str) -> None:
    assert (await client.delete(f"{GROUPS}/{group}", headers=admin.auth)).status_code == 204
    assert (await client.get(f"{GROUPS}/{group}", headers=admin.auth)).status_code == 404


async def test_member_cannot_delete_group(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.delete(f"{GROUPS}/{group}", headers=member.auth)
    assert resp.status_code == 403


async def test_delete_removes_memberships_for_everyone(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.delete(f"{GROUPS}/{group}", headers=admin.auth)

    assert (await client.get(GROUPS, headers=member.auth)).json() == []


async def test_non_member_cannot_delete_group(
    client: AsyncClient, outsider: User, group: str
) -> None:
    resp = await client.delete(f"{GROUPS}/{group}", headers=outsider.auth)
    assert resp.status_code == 404
