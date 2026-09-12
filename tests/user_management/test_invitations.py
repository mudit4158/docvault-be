"""Invitation lifecycle: invite, list pending, accept, decline."""

from httpx import AsyncClient

from tests.user_management.conftest import User, add_member, make_user

GROUPS = "/api/v1/groups"
INVITES = "/api/v1/invitations"


# --- issuing --------------------------------------------------------------


async def test_admin_can_invite_existing_user(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["group_name"] == "Sharma Family"
    assert body["invited_by"]["display_name"] == "Mudit"


async def test_invite_rejects_unregistered_phone(
    client: AsyncClient, admin: User, group: str
) -> None:
    """Group invites reach existing users only; platform invites are future scope."""
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": "+919999999999"}, headers=admin.auth
    )
    assert resp.status_code == 404


async def test_member_cannot_invite(
    client: AsyncClient, admin: User, member: User, outsider: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": outsider.phone}, headers=member.auth
    )
    assert resp.status_code == 403


async def test_cannot_invite_an_existing_member(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    assert resp.status_code == 409


async def test_cannot_issue_a_second_pending_invitation(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    assert resp.status_code == 409


async def test_declined_invitation_can_be_reissued(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    first = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    await client.post(f"{INVITES}/{first.json()['id']}/decline", headers=member.auth)

    again = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    assert again.status_code == 201
    assert again.json()["status"] == "pending"


async def test_invite_rejects_malformed_phone(
    client: AsyncClient, admin: User, group: str
) -> None:
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": "98765"}, headers=admin.auth
    )
    assert resp.status_code == 422


# --- listing --------------------------------------------------------------


async def test_invitee_sees_pending_invitation(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    resp = await client.get(INVITES, headers=member.auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["group_name"] == "Sharma Family"
    assert resp.json()[0]["invited_by"]["display_name"] == "Mudit"


async def test_others_do_not_see_the_invitation(
    client: AsyncClient, admin: User, member: User, outsider: User, group: str
) -> None:
    await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    assert (await client.get(INVITES, headers=outsider.auth)).json() == []


async def test_accepted_invitation_leaves_the_list(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    """An accepted invitation is already visible as a group membership."""
    await add_member(client, group, admin, member)
    assert (await client.get(INVITES, headers=member.auth)).json() == []


async def test_declined_invitations_are_still_listed(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    """So an invitee can find one they dismissed by accident."""
    invite = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    await client.post(f"{INVITES}/{invite.json()['id']}/decline", headers=member.auth)

    listed = (await client.get(INVITES, headers=member.auth)).json()
    assert len(listed) == 1
    assert listed[0]["status"] == "declined"


async def test_status_filter_narrows_the_list(
    client: AsyncClient, admin: User, member: User, outsider: User, group: str
) -> None:
    # One declined...
    declined = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    await client.post(f"{INVITES}/{declined.json()['id']}/decline", headers=member.auth)
    # ...and one still pending, for a different person.
    await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": outsider.phone}, headers=admin.auth
    )

    pending = (await client.get(f"{INVITES}?status=pending", headers=outsider.auth)).json()
    assert [i["status"] for i in pending] == ["pending"]

    only_declined = (
        await client.get(f"{INVITES}?status=declined", headers=member.auth)
    ).json()
    assert [i["status"] for i in only_declined] == ["declined"]

    assert (await client.get(f"{INVITES}?status=pending", headers=member.auth)).json() == []


async def test_listing_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(INVITES)).status_code == 401


# --- accepting ------------------------------------------------------------


async def test_accept_joins_the_group(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    await add_member(client, group, admin, member)

    groups = await client.get(GROUPS, headers=member.auth)
    assert len(groups.json()) == 1
    assert groups.json()[0]["my_role"] == "member"


async def test_accept_is_idempotent(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    invitation_id = await add_member(client, group, admin, member)
    again = await client.post(f"{INVITES}/{invitation_id}/accept", headers=member.auth)
    assert again.status_code == 204

    detail = await client.get(f"{GROUPS}/{group}", headers=admin.auth)
    assert detail.json()["member_count"] == 2  # not 3


async def test_cannot_accept_someone_elses_invitation(
    client: AsyncClient, admin: User, member: User, outsider: User, group: str
) -> None:
    invite = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    resp = await client.post(
        f"{INVITES}/{invite.json()['id']}/accept", headers=outsider.auth
    )
    assert resp.status_code == 404


async def test_cannot_accept_after_declining(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    invite = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    invitation_id = invite.json()["id"]
    await client.post(f"{INVITES}/{invitation_id}/decline", headers=member.auth)

    resp = await client.post(f"{INVITES}/{invitation_id}/accept", headers=member.auth)
    assert resp.status_code == 409


async def test_accept_unknown_invitation_is_404(client: AsyncClient, member: User) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    resp = await client.post(f"{INVITES}/{unknown}/accept", headers=member.auth)
    assert resp.status_code == 404


# --- declining ------------------------------------------------------------


async def test_decline_removes_it_from_pending(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    invite = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": member.phone}, headers=admin.auth
    )
    resp = await client.post(f"{INVITES}/{invite.json()['id']}/decline", headers=member.auth)
    assert resp.status_code == 204

    # Gone from pending, but still retrievable as declined so the invitee can
    # find one they dismissed by accident.
    assert (await client.get(f"{INVITES}?status=pending", headers=member.auth)).json() == []
    assert (await client.get(GROUPS, headers=member.auth)).json() == []


async def test_cannot_decline_after_accepting(
    client: AsyncClient, admin: User, member: User, group: str
) -> None:
    invitation_id = await add_member(client, group, admin, member)
    resp = await client.post(f"{INVITES}/{invitation_id}/decline", headers=member.auth)
    assert resp.status_code == 409


# --- member cap -----------------------------------------------------------


async def test_invite_blocked_once_group_is_full(
    client: AsyncClient, admin: User, group: str, monkeypatch
) -> None:
    """The cap counts the admin — handoff screen 18 shows '5 of 20 members'
    listing the admin plus four members."""
    from app.config import settings

    monkeypatch.setattr(settings, "group_member_cap", 2)

    filler = await make_user(client, "+919000000201", "Papa")
    await add_member(client, group, admin, filler)  # group now at 2 of 2

    one_too_many = await make_user(client, "+919000000202", "Amma")
    resp = await client.post(
        f"{GROUPS}/{group}/invite", json={"phone": one_too_many.phone}, headers=admin.auth
    )
    assert resp.status_code == 409
    assert "limit" in resp.json()["detail"].lower()


async def test_cap_is_rechecked_at_accept_time(
    client: AsyncClient, admin: User, group: str, monkeypatch
) -> None:
    """Invitations issued while there was room must not overfill the group."""
    from app.config import settings

    monkeypatch.setattr(settings, "group_member_cap", 3)

    a = await make_user(client, "+919000000203", "Riya")
    b = await make_user(client, "+919000000204", "Nikhil")

    # Both invited while the group has room (1 of 3).
    inv_a = (
        await client.post(
            f"{GROUPS}/{group}/invite", json={"phone": a.phone}, headers=admin.auth
        )
    ).json()["id"]
    inv_b = (
        await client.post(
            f"{GROUPS}/{group}/invite", json={"phone": b.phone}, headers=admin.auth
        )
    ).json()["id"]

    assert (await client.post(f"{INVITES}/{inv_a}/accept", headers=a.auth)).status_code == 204

    # Group is now full at 3; shrink the cap to prove the re-check runs.
    monkeypatch.setattr(settings, "group_member_cap", 2)
    resp = await client.post(f"{INVITES}/{inv_b}/accept", headers=b.auth)
    assert resp.status_code == 409
