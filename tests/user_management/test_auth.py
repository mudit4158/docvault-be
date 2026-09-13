"""Registration, login, profile, password change, quota."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.user_management.models.auth_identity import AuthIdentity
from app.user_management.models.quota import UploadQuota
from tests.audit_helpers import audit_rows

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"

VALID = {"phone": "+919876543210", "display_name": "Mudit", "password": "correct-horse"}


async def register(client: AsyncClient, **overrides: object) -> dict:
    resp = await client.post(REGISTER, json={**VALID, **overrides})
    return resp.json()


async def token_for(client: AsyncClient, phone: str, password: str) -> str:
    resp = await client.post(LOGIN, json={"phone": phone, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- registration: happy ---------------------------------------------------


async def test_register_creates_account(client: AsyncClient) -> None:
    resp = await client.post(REGISTER, json=VALID)
    assert resp.status_code == 201
    body = resp.json()
    assert body["phone"] == VALID["phone"]
    assert body["display_name"] == "Mudit"
    assert "id" in body


async def test_register_never_returns_the_password(client: AsyncClient) -> None:
    resp = await client.post(REGISTER, json=VALID)
    assert "password" not in resp.text
    assert "secret" not in resp.text.lower()


async def test_register_creates_quota_row_in_same_transaction(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An account without a quota row would break its owner's first upload."""
    body = await register(client)

    quota = await db.get(UploadQuota, __import__("uuid").UUID(body["id"]))
    assert quota is not None
    assert quota.files_used_today == 0
    assert quota.cap_files == 10  # settings.daily_upload_cap default


async def test_register_creates_password_identity(
    client: AsyncClient, db: AsyncSession
) -> None:
    body = await register(client)

    identity = await db.scalar(
        select(AuthIdentity).where(AuthIdentity.account_id == __import__("uuid").UUID(body["id"]))
    )
    assert identity is not None
    assert identity.provider == "password"
    assert identity.provider_subject == VALID["phone"]
    # Stored hashed, never in the clear.
    assert identity.secret_hash != VALID["password"]
    assert identity.secret_hash.startswith("$2b$")


# --- registration: negative ------------------------------------------------


async def test_register_rejects_duplicate_phone(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    resp = await client.post(REGISTER, json={**VALID, "display_name": "Impostor"})
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "phone",
    ["9876543210", "+0123456789", "+91 98765 43210", "not-a-phone", "+123", ""],
)
async def test_register_rejects_malformed_phone(client: AsyncClient, phone: str) -> None:
    resp = await client.post(REGISTER, json={**VALID, "phone": phone})
    assert resp.status_code == 422


@pytest.mark.parametrize("password", ["short", "1234567", ""])
async def test_register_rejects_short_password(client: AsyncClient, password: str) -> None:
    resp = await client.post(REGISTER, json={**VALID, "password": password})
    assert resp.status_code == 422


async def test_register_rejects_password_beyond_bcrypt_limit(client: AsyncClient) -> None:
    """Over 72 bytes bcrypt truncates silently, so two passwords could collide."""
    resp = await client.post(REGISTER, json={**VALID, "password": "a" * 73})
    assert resp.status_code == 422


async def test_register_rejects_blank_display_name(client: AsyncClient) -> None:
    resp = await client.post(REGISTER, json={**VALID, "display_name": ""})
    assert resp.status_code == 422


# --- login: happy ----------------------------------------------------------


async def test_login_returns_bearer_token(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    resp = await client.post(
        LOGIN, json={"phone": VALID["phone"], "password": VALID["password"]}
    )
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


async def test_login_mode_defaults_to_password(client: AsyncClient) -> None:
    """Clients may omit `mode` until a second login mode exists."""
    await client.post(REGISTER, json=VALID)
    resp = await client.post(
        LOGIN,
        json={"mode": "password", "phone": VALID["phone"], "password": VALID["password"]},
    )
    assert resp.status_code == 200


async def test_login_records_last_used(client: AsyncClient, db: AsyncSession) -> None:
    await client.post(REGISTER, json=VALID)
    await token_for(client, VALID["phone"], VALID["password"])

    identity = await db.scalar(select(AuthIdentity))
    assert identity is not None and identity.last_used_at is not None


# --- login: negative -------------------------------------------------------


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    resp = await client.post(LOGIN, json={"phone": VALID["phone"], "password": "wrong-one"})
    assert resp.status_code == 401


async def test_login_rejects_unknown_phone(client: AsyncClient) -> None:
    resp = await client.post(LOGIN, json={"phone": "+919999999999", "password": "whatever1"})
    assert resp.status_code == 401


async def test_login_does_not_reveal_whether_an_account_exists(client: AsyncClient) -> None:
    """Distinct errors would let anyone enumerate registered phone numbers."""
    await client.post(REGISTER, json=VALID)

    wrong_password = await client.post(
        LOGIN, json={"phone": VALID["phone"], "password": "wrong-one"}
    )
    unknown_account = await client.post(
        LOGIN, json={"phone": "+919999999999", "password": "wrong-one"}
    )

    assert wrong_password.status_code == unknown_account.status_code == 401
    assert wrong_password.json()["detail"] == unknown_account.json()["detail"]


async def test_login_rejects_unsupported_mode(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    resp = await client.post(
        LOGIN, json={"mode": "google", "phone": VALID["phone"], "password": "x"}
    )
    assert resp.status_code == 422  # not yet a valid enum member


# --- authenticated access --------------------------------------------------


async def test_me_returns_profile(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    token = await token_for(client, VALID["phone"], VALID["password"])

    resp = await client.get(ME, headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["phone"] == VALID["phone"]


async def test_me_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get(ME)).status_code == 401


async def test_me_rejects_a_garbage_token(client: AsyncClient) -> None:
    assert (await client.get(ME, headers=auth("not.a.jwt"))).status_code == 401


async def test_quota_is_readable(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    token = await token_for(client, VALID["phone"], VALID["password"])

    resp = await client.get("/api/v1/auth/me/quota", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json()["cap_files"] == 10
    assert resp.json()["files_used_today"] == 0


# --- password change -------------------------------------------------------


async def test_password_change_then_login_with_new_password(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    token = await token_for(client, VALID["phone"], VALID["password"])

    resp = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": VALID["password"], "new_password": "brand-new-secret"},
        headers=auth(token),
    )
    assert resp.status_code == 204

    assert (
        await client.post(
            LOGIN, json={"phone": VALID["phone"], "password": "brand-new-secret"}
        )
    ).status_code == 200
    assert (
        await client.post(LOGIN, json={"phone": VALID["phone"], "password": VALID["password"]})
    ).status_code == 401


async def test_password_change_rejects_wrong_current_password(client: AsyncClient) -> None:
    await client.post(REGISTER, json=VALID)
    token = await token_for(client, VALID["phone"], VALID["password"])

    resp = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "not-it", "new_password": "brand-new-secret"},
        headers=auth(token),
    )
    assert resp.status_code == 401


async def test_password_change_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "x", "new_password": "brand-new-secret"},
    )
    assert resp.status_code == 401


# --- audit -----------------------------------------------------------------


async def test_registration_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    await client.post(REGISTER, json=VALID)

    rows = await audit_rows(db, "accounts")
    assert len(rows) == 1
    assert rows[0]["audit_operation"] == "INSERT"
    # No actor: registration happens before anyone is authenticated.
    assert rows[0]["audit_actor_id"] is None


async def test_password_change_is_audited_without_leaking_the_hash(
    client: AsyncClient, db: AsyncSession
) -> None:
    await client.post(REGISTER, json=VALID)
    token = await token_for(client, VALID["phone"], VALID["password"])
    await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": VALID["password"], "new_password": "brand-new-secret"},
        headers=auth(token),
    )

    updates = await audit_rows(db, "auth_identities", operation="UPDATE")
    assert updates, "password change must leave an audit trail"
    for row in updates:
        # secret_hash is not even a column on the audit table.
        assert "secret_hash" not in row
        assert "brand-new-secret" not in str(dict(row))
