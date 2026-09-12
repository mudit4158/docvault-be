"""The audit framework: generic capture, pluggable per-table storage."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.audit import acting_as, audit_table_for, audited_models
from app.user_management.models.account import Account
from app.user_management.models.auth_identity import AuthIdentity
from app.user_management.models.group import Group
from app.user_management.models.membership import Membership
from tests.audit_helpers import audit_column_names, audit_rows


@pytest.fixture
async def account(db: AsyncSession) -> Account:
    acc = Account(phone="+919000000001", display_name="Audit Subject")
    db.add(acc)
    await db.flush()
    return acc


# --- table generation -----------------------------------------------------


async def test_every_audited_model_gets_its_own_table() -> None:
    """One shadow table per audited table, not one shared table."""
    assert audited_models(), "no models registered as audited"

    for source in ("accounts", "groups", "memberships", "invitations", "auth_identities"):
        table = audit_table_for(source)
        assert table is not None, f"{source} has no audit table"
        assert table.name == f"{source}_audit"


async def test_audit_table_mirrors_source_columns(db: AsyncSession) -> None:
    """Values land in typed columns, not a JSON blob."""
    columns = await audit_column_names(db, "accounts")

    # Framework columns.
    assert {"audit_id", "audit_operation", "audit_actor_id", "audit_at"} <= columns
    # Mirrored source columns.
    assert {"id", "phone", "display_name", "created_at"} <= columns


async def test_excluded_columns_do_not_exist_in_the_audit_table(db: AsyncSession) -> None:
    """Stronger than filtering at write time: the secret has nowhere to go."""
    columns = await audit_column_names(db, "auth_identities")

    assert "secret_hash" not in columns
    assert "provider" in columns  # the rest of the row is still mirrored


async def test_unaudited_model_gets_no_table() -> None:
    """Only models opting in with __audited__ are captured."""
    assert audit_table_for("tags") is None
    assert audit_table_for("documents") is None


# --- capture --------------------------------------------------------------


async def test_insert_is_recorded(db: AsyncSession) -> None:
    db.add(Account(phone="+919000000002", display_name="Riya"))
    await db.flush()

    rows = await audit_rows(db, "accounts")
    assert len(rows) == 1
    assert rows[0]["audit_operation"] == "INSERT"
    assert rows[0]["phone"] == "+919000000002"
    assert rows[0]["display_name"] == "Riya"


async def test_update_records_changed_fields_and_full_snapshot(
    db: AsyncSession, account: Account
) -> None:
    account.display_name = "Riya Sharma"
    await db.flush()

    rows = await audit_rows(db, "accounts", operation="UPDATE")
    assert len(rows) == 1
    assert rows[0]["audit_changed_fields"] == ["display_name"]
    # The snapshot is the whole row after the change...
    assert rows[0]["display_name"] == "Riya Sharma"
    # ...including columns that did not change, so a row can be reconstructed
    # from a single audit entry.
    assert rows[0]["phone"] == "+919000000001"


async def test_delete_records_the_state_being_destroyed(
    db: AsyncSession, account: Account
) -> None:
    await db.delete(account)
    await db.flush()

    rows = await audit_rows(db, "accounts", operation="DELETE")
    assert len(rows) == 1
    assert rows[0]["phone"] == "+919000000001"


async def test_actor_is_attributed(db: AsyncSession, account: Account) -> None:
    actor = uuid.uuid4()
    with acting_as(actor):
        db.add(Group(name="Sharma Family", created_by=account.id))
        await db.flush()

    rows = await audit_rows(db, "groups")
    assert rows[0]["audit_actor_id"] == actor


async def test_composite_primary_key_is_mirrored(db: AsyncSession, account: Account) -> None:
    group = Group(name="Flat 402", created_by=account.id)
    db.add(group)
    await db.flush()

    db.add(Membership(group_id=group.id, user_id=account.id, role="admin"))
    await db.flush()

    rows = await audit_rows(db, "memberships")
    assert len(rows) == 1
    # Both halves of the composite key are real, queryable columns.
    assert rows[0]["group_id"] == group.id
    assert rows[0]["user_id"] == account.id
    assert rows[0]["role"] == "admin"


async def test_enum_column_is_mirrored_as_text(db: AsyncSession, account: Account) -> None:
    """Audit history must accept values a later migration retires from the enum."""
    table = audit_table_for("memberships")
    assert table is not None
    assert "VARCHAR" in str(table.c.role.type).upper()


# --- negative / safety ----------------------------------------------------


async def test_secret_is_never_written_to_the_trail(
    db: AsyncSession, account: Account
) -> None:
    db.add(
        AuthIdentity(
            account_id=account.id,
            provider="password",
            provider_subject=account.phone,
            secret_hash="$2b$12$supersecrethashvalue",
        )
    )
    await db.flush()

    rows = await audit_rows(db, "auth_identities")
    assert len(rows) == 1
    assert "supersecrethashvalue" not in str(dict(rows[0]))


async def test_audit_tables_do_not_audit_themselves(
    db: AsyncSession, account: Account
) -> None:
    """Otherwise every write would recurse."""
    account.display_name = "Changed"
    await db.flush()

    assert audit_table_for("accounts_audit") is None


async def test_no_row_when_nothing_actually_changed(
    db: AsyncSession, account: Account
) -> None:
    """Re-assigning the same value must not create a noise row."""
    account.display_name = "Audit Subject"  # identical to current
    await db.flush()

    assert await audit_rows(db, "accounts", operation="UPDATE") == []


async def test_unauthenticated_action_records_null_actor(db: AsyncSession) -> None:
    """Registration happens before an actor exists."""
    db.add(Account(phone="+919000000003", display_name="Anon"))
    await db.flush()

    rows = await audit_rows(db, "accounts")
    assert rows[0]["audit_actor_id"] is None


# --- pluggability ---------------------------------------------------------


async def test_sinks_are_selectable_by_name() -> None:
    """The storage strategy is configuration, not a code change."""
    from app.shared.audit import get_sink

    assert get_sink("per_table").name == "per_table"
    assert get_sink("none").name == "none"
    assert get_sink("single_table").name == "single_table"

    with pytest.raises(ValueError, match="Unknown audit sink"):
        get_sink("does_not_exist")


async def test_custom_sink_can_be_registered() -> None:
    """A new storage backend is a subclass plus one call."""
    from app.shared.audit import AuditSink, get_sink, register_sink

    class MemorySink(AuditSink):
        name = "test_memory"
        collected: list = []

        def emit(self, session, records):
            self.collected.extend(records)

    register_sink(MemorySink)
    assert isinstance(get_sink("test_memory"), MemorySink)
