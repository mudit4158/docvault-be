"""Member listing, removal, leaving, and admin transfer.

The recurring theme: a group must always have exactly one admin, and no path
may leave it with zero.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.audit_helpers import audit_rows
from tests.user_management.conftest import User, add_member

GROUPS = "/api/v1/groups"


# --- listing --------------------------------------------------------------


async def test_members_are_listed_with_roles(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.get(f"{GROUPS}/{group}/members", headers=admin.auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2

    by_name = {m["account"]["display_name"]: m for m in body}
    assert by_name["Mudit"]["role"] == "admin"
    assert by_name["Riya"]["role"] == "member"


async def test_member_can_list_members(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.get(f"{GROUPS}/{group}/members", headers=member.auth)
    assert resp.status_code == 200


async def test_non_member_cannot_list_members(
    client: AsyncClient, outsider: User, group: str
) -> None:
    resp = await client.get(f"{GROUPS}/{group}/members", headers=outsider.auth)
    assert resp.status_code == 404


async def test_member_list_requires_auth(client: AsyncClient, group: str) -> None:
    assert (await client.get(f"{GROUPS}/{group}/members")).status_code == 401


# --- removal --------------------------------------------------------------


async def test_admin_can_remove_a_member(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.delete(
        f"{GROUPS}/{group}/members/{member.id}", headers=admin.auth
    )
    assert resp.status_code == 204

    assert (await client.get(GROUPS, headers=member.auth)).json() == []
    assert len((await client.get(f"{GROUPS}/{group}/members", headers=admin.auth)).json()) == 1


async def test_member_cannot_remove_another_member(
    client: AsyncClient, admin: User, member: User, outsider: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await add_member(client, group, admin, outsider)

    resp = await client.delete(
        f"{GROUPS}/{group}/members/{outsider.id}", headers=member.auth
    )
    assert resp.status_code == 403


async def test_admin_cannot_remove_themselves(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    """Would leave the group with no admin."""
    await add_member(client, group, admin, member)

    resp = await client.delete(f"{GROUPS}/{group}/members/{admin.id}", headers=admin.auth)
    assert resp.status_code == 409
    assert "transfer" in resp.json()["detail"].lower()


async def test_removing_a_non_member_is_404(
    client: AsyncClient, admin: User, outsider: User, group: str
) -> None:
    resp = await client.delete(
        f"{GROUPS}/{group}/members/{outsider.id}", headers=admin.auth
    )
    assert resp.status_code == 404


# --- leaving --------------------------------------------------------------


async def test_member_can_leave(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.delete(f"{GROUPS}/{group}/members/me", headers=member.auth)
    assert resp.status_code == 204
    assert (await client.get(GROUPS, headers=member.auth)).json() == []


async def test_sole_admin_cannot_leave_while_others_remain(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.delete(f"{GROUPS}/{group}/members/me", headers=admin.auth)
    assert resp.status_code == 409
    assert "transfer" in resp.json()["detail"].lower()


async def test_last_member_leaving_deletes_the_group(
    client: AsyncClient, admin: User, group: str
) -> None:
    """An empty group is unreachable by anyone, so it is removed."""
    resp = await client.delete(f"{GROUPS}/{group}/members/me", headers=admin.auth)
    assert resp.status_code == 204

    assert (await client.get(f"{GROUPS}/{group}", headers=admin.auth)).status_code == 404


async def test_admin_can_leave_after_transferring(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=admin.auth,
    )

    resp = await client.delete(f"{GROUPS}/{group}/members/me", headers=admin.auth)
    assert resp.status_code == 204


async def test_non_member_cannot_leave(
    client: AsyncClient, outsider: User, group: str
) -> None:
    resp = await client.delete(f"{GROUPS}/{group}/members/me", headers=outsider.auth)
    assert resp.status_code == 404


# --- admin transfer -------------------------------------------------------


async def test_transfer_swaps_both_roles(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=admin.auth,
    )
    assert resp.status_code == 204

    assert (await client.get(f"{GROUPS}/{group}", headers=member.auth)).json()["my_role"] == "admin"
    assert (await client.get(f"{GROUPS}/{group}", headers=admin.auth)).json()["my_role"] == "member"


async def test_exactly_one_admin_after_transfer(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=admin.auth,
    )

    members = (await client.get(f"{GROUPS}/{group}/members", headers=member.auth)).json()
    assert [m["role"] for m in members].count("admin") == 1


async def test_former_admin_loses_admin_powers(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=admin.auth,
    )

    resp = await client.delete(f"{GROUPS}/{group}", headers=admin.auth)
    assert resp.status_code == 403


async def test_member_cannot_transfer_admin(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    resp = await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=member.auth,
    )
    assert resp.status_code == 403


async def test_cannot_transfer_to_a_non_member(
    client: AsyncClient, admin: User, outsider: User, group: str
) -> None:
    resp = await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": outsider.id},
        headers=admin.auth,
    )
    assert resp.status_code == 404


async def test_cannot_transfer_to_self(client: AsyncClient, admin: User, group: str) -> None:
    resp = await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": admin.id},
        headers=admin.auth,
    )
    assert resp.status_code == 409


# --- audit ----------------------------------------------------------------


async def test_group_actions_are_attributed_to_the_actor(
    client: AsyncClient, db: AsyncSession, admin: User, group: str
) -> None:
    rows = await audit_rows(db, "groups")
    assert len(rows) == 1
    assert rows[0]["audit_operation"] == "INSERT"
    assert str(rows[0]["audit_actor_id"]) == admin.id
    assert rows[0]["name"] == "Sharma Family"


async def test_role_change_is_audited_with_before_and_after(
    client: AsyncClient, db: AsyncSession, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.post(
        f"{GROUPS}/{group}/transfer-admin",
        json={"new_admin_id": member.id},
        headers=admin.auth,
    )

    rows = await audit_rows(db, "memberships", operation="UPDATE")
    # Both sides of the swap are recorded: promotion and demotion.
    assert len(rows) == 2
    # `role` is the post-change value; the prior one is in audit_changed_fields' company.
    assert {r["role"] for r in rows} == {"admin", "member"}
    for row in rows:
        assert row["audit_changed_fields"] == ["role"]
        assert str(row["audit_actor_id"]) == admin.id


async def test_member_removal_is_audited(
    client: AsyncClient, db: AsyncSession, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    await client.delete(f"{GROUPS}/{group}/members/{member.id}", headers=admin.auth)

    rows = await audit_rows(db, "memberships", operation="DELETE")
    assert len(rows) == 1
    assert str(rows[0]["audit_actor_id"]) == admin.id
    # The removed member's row is preserved in typed columns.
    assert str(rows[0]["user_id"]) == member.id
