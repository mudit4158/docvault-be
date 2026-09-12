"""Reading the audit trail in tests.

Audit tables are generated, not declared, so they are queried as Core tables
rather than through an ORM model.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.audit import audit_table_for


async def audit_rows(
    db: AsyncSession,
    source_table: str,
    operation: str | None = None,
) -> list[Any]:
    """Audit rows for one source table, oldest first."""
    table = audit_table_for(source_table)
    assert table is not None, (
        f"No audit table for {source_table!r}. Either the model is missing "
        f"__audited__ = True, or it is not imported in app/registry.py."
    )

    stmt = select(table).order_by(table.c.audit_at, table.c.audit_id)
    if operation:
        stmt = stmt.where(table.c.audit_operation == operation)

    return list((await db.execute(stmt)).mappings().all())


async def audit_column_names(db: AsyncSession, source_table: str) -> set[str]:
    table = audit_table_for(source_table)
    assert table is not None
    return {c.name for c in table.columns}
