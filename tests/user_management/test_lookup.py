"""Account lookup — resolving a phone number to a person before inviting them."""

from httpx import AsyncClient

from tests.user_management.conftest import User, make_user

LOOKUP = "/api/v1/accounts/lookup"


async def test_resolves_a_registered_number(client: AsyncClient, admin: User) -> None:
    resp = await client.post(LOOKUP, json={"phone": admin.phone}, headers=admin.auth)

    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Mudit"
    assert body["phone"] == admin.phone
    assert body["id"] == admin.id


async def test_lookup_returns_only_minimal_fields(client: AsyncClient, admin: User) -> None:
    """A lookup is a privacy surface; it must not leak more than the invite needs."""
    resp = await client.post(LOOKUP, json={"phone": admin.phone}, headers=admin.auth)

    assert set(resp.json()) == {"id", "phone", "display_name"}


async def test_unregistered_number_explains_what_to_do(
    client: AsyncClient, admin: User
) -> None:
    resp = await client.post(
        LOOKUP, json={"phone": "+919111111111"}, headers=admin.auth
    )

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "does not have an active DocVault account" in detail
    assert "sign up" in detail.lower()


async def test_lookup_requires_authentication(client: AsyncClient) -> None:
    """Otherwise anyone could enumerate which numbers are registered."""
    resp = await client.post(LOOKUP, json={"phone": "+919000000101"})
    assert resp.status_code == 401


async def test_lookup_rejects_a_malformed_number(client: AsyncClient, admin: User) -> None:
    resp = await client.post(LOOKUP, json={"phone": "98765"}, headers=admin.auth)
    assert resp.status_code == 422


async def test_lookup_finds_another_user(
    client: AsyncClient, admin: User, member: User
) -> None:
    resp = await client.post(LOOKUP, json={"phone": member.phone}, headers=admin.auth)

    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Riya"


async def test_resolved_user_can_then_be_invited(
    client: AsyncClient, admin: User, group: str
) -> None:
    """The lookup and the invite agree on who exists."""
    invitee = await make_user(client, "+919000000301", "Papa")

    lookup = await client.post(LOOKUP, json={"phone": invitee.phone}, headers=admin.auth)
    assert lookup.status_code == 200

    invite = await client.post(
        f"/api/v1/groups/{group}/invite",
        json={"phone": invitee.phone},
        headers=admin.auth,
    )
    assert invite.status_code == 201
