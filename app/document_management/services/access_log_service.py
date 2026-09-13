"""The per-document access log (PRD §4.8). Append-only.

Rules in docs/access_log.md:
  - no UPDATE and no DELETE, anywhere
  - written in the SAME transaction as the action it records, so a rolled-back
    action never leaves a log entry claiming it happened
  - written only after the permission check passes — a refused attempt is not
    an access

This is a product feature the owner reads. It is separate from the automatic
audit trail in app/shared/audit, which covers every table.
"""

import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.access_log import AccessLog
from app.document_management.schemas.access_log import AccessLogEntry, AccessLogPage
from app.document_management.schemas.common import PersonSummary
from app.document_management.services.access_service import AccessService
from app.shared.clock import utcnow
from app.shared.pagination import PageParams
from app.user_management.models.account import Account

AccessEvent = Literal[
    "upload", "view", "download", "share", "revoke", "delete", "restore", "rename"
]


class AccessLogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self, document_id: uuid.UUID, actor_id: uuid.UUID | None, event_type: AccessEvent
    ) -> None:
        self.db.add(
            AccessLog(
                id=uuid.uuid4(),
                document_id=document_id,
                actor_id=actor_id,
                event_type=event_type,
                # Set here rather than by the database default, which on some
                # backends has only second precision and would make events in
                # the same second unorderable.
                created_at=utcnow(),
            )
        )

    async def list_for_owner(
        self, document_id: uuid.UUID, account_id: uuid.UUID, page: PageParams
    ) -> AccessLogPage:
        """Owner only (screen 19 is labelled "OWNER ONLY").

        A member who can see the document still cannot see who else opened it.
        Reading the log is not itself logged — otherwise reading the log would
        grow the log.
        """
        await AccessService(self.db).require_owner(document_id, account_id)

        in_document = AccessLog.document_id == document_id
        total = await self.db.scalar(select(func.count()).select_from(AccessLog).where(in_document))
        downloads = await self.db.scalar(
            select(func.count())
            .select_from(AccessLog)
            .where(in_document, AccessLog.event_type == "download")
        )

        rows = await self.db.execute(
            select(AccessLog, Account.display_name)
            .outerjoin(Account, Account.id == AccessLog.actor_id)
            .where(in_document)
            .order_by(AccessLog.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )

        items = [
            AccessLogEntry(
                id=log.id,
                event_type=log.event_type,
                actor=(
                    PersonSummary(id=log.actor_id, display_name=name)
                    if log.actor_id is not None and name is not None
                    else None
                ),
                created_at=log.created_at,
            )
            for log, name in rows.all()
        ]

        return AccessLogPage(
            items=items,
            total=total or 0,
            page=page.page,
            page_size=page.page_size,
            has_next=page.offset + len(items) < (total or 0),
            download_count=downloads or 0,
        )
