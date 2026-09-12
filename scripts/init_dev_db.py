"""Create all tables directly from the models — LOCAL DEV ONLY.

For poking at the API on SQLite without standing up Postgres. It bypasses
Alembic entirely, so it produces no migration history and must never be
pointed at a shared or production database.

For anything real:  alembic upgrade head

    python scripts/init_dev_db.py            # create missing tables
    python scripts/init_dev_db.py --reset    # drop everything first
"""

import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

# Registers every model AND the generated audit tables, in that order.
# Importing this is what guarantees the schema is complete.
import app.registry  # noqa: F401
from app.config import settings
from app.shared.db.base import Base


async def main() -> None:
    url = settings.database_url
    if not url.startswith("sqlite"):
        print(f"Refusing to run against a non-SQLite database:\n  {url}\n")
        print("This script is for local SQLite only. Use: alembic upgrade head")
        sys.exit(1)

    reset = "--reset" in sys.argv

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    source = sorted(t for t in Base.metadata.tables if not t.endswith("_audit"))
    audit = sorted(t for t in Base.metadata.tables if t.endswith("_audit"))

    print(f"{'Recreated' if reset else 'Created'} {len(Base.metadata.tables)} tables in {url}")
    print(f"\n  source tables ({len(source)}):")
    for name in source:
        print(f"    - {name}")
    print(f"\n  generated audit tables ({len(audit)}):")
    for name in audit:
        print(f"    - {name}")


if __name__ == "__main__":
    asyncio.run(main())
