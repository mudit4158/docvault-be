"""Helpers for user_management tests."""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"

# Upper + lower + digit + special, to satisfy the registration complexity policy.
PASSWORD = "Correct-Horse-Battery1"


@dataclass
class User:
    """A registered user plus a ready-to-use auth header."""

    id: str
    phone: str
    display_name: str
    token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def make_user(client: AsyncClient, phone: str, name: str) -> User:
    resp = await client.post(
        REGISTER, json={"phone": phone, "display_name": name, "password": PASSWORD}
    )
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["id"]

    login = await client.post(LOGIN, json={"phone": phone, "password": PASSWORD})
    assert login.status_code == 200, login.text

    return User(
        id=account_id, phone=phone, display_name=name, token=login.json()["access_token"]
    )


@pytest.fixture
async def admin(client: AsyncClient) -> User:
    return await make_user(client, "+919000000101", "Mudit")


@pytest.fixture
async def member(client: AsyncClient) -> User:
    return await make_user(client, "+919000000102", "Riya")


@pytest.fixture
async def outsider(client: AsyncClient) -> User:
    """Registered, but not in any group — used for access-control tests."""
    return await make_user(client, "+919000000103", "Nikhil")


@pytest.fixture
async def group(client: AsyncClient, admin: User) -> str:
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Sharma Family", "description": "Everyday identity papers"},
        headers=admin.auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def add_member(client: AsyncClient, group_id: str, admin: User, user: User) -> str:
    """Invite a user and have them accept. Returns the invitation id."""
    invite = await client.post(
        f"/api/v1/groups/{group_id}/invite",
        json={"phone": user.phone},
        headers=admin.auth,
    )
    assert invite.status_code == 201, invite.text
    invitation_id = invite.json()["id"]

    accept = await client.post(
        f"/api/v1/invitations/{invitation_id}/accept", headers=user.auth
    )
    assert accept.status_code == 204, accept.text
    return invitation_id
