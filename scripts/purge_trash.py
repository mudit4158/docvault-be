"""Permanently remove files that have been in the trash past the retention window.

Run once a day (cron, Cloud Scheduler...). Scheduling is not set up yet —
tracked in docs/TRACKER.md. Safe to run repeatedly.

    python scripts/purge_trash.py
"""

import asyncio

import app.registry  # noqa: F401
from app.document_management.services.document_service import DocumentService
from app.shared.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        purged = await DocumentService(session).purge_expired()
        await session.commit()
    print(f"Purged {purged} document file(s).")


if __name__ == "__main__":
    asyncio.run(main())
