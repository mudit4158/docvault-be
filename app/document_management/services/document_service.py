"""Document service — the SAMPLE FLOW for document_management.

`list_for_owner` is the reference implementation. It demonstrates the three
things every read path in this module must do:

  1. Filter `deleted_at IS NULL` — soft-deleted documents are invisible.
  2. Scope to the caller — never return another account's documents.
  3. Return a PagedResponse — the vault must stay fast at 500+ documents.

See app/document_management/docs/document_lifecycle.md for the full spec of
the features that are not built yet.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.document import Document
from app.document_management.schemas.document import DocumentListFilters, DocumentResponse
from app.shared.pagination import PagedResponse, PageParams


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        filters: DocumentListFilters,
        page: PageParams,
    ) -> PagedResponse[DocumentResponse]:
        """List the caller's active documents, newest first.

        Serves both the list and grid views — grid is a client-side layout
        toggle over the same payload, not a separate endpoint.
        """
        # Soft-delete filter is mandatory on every read path in this module.
        conditions = [
            Document.owner_id == owner_id,
            Document.deleted_at.is_(None),
        ]

        if filters.q:
            conditions.append(Document.name.ilike(f"%{filters.q}%"))

        if filters.doc_type:
            conditions.append(Document.doc_type == filters.doc_type)

        # NOTE: `filters.tag` requires a join through DocTag -> Tag.
        # Not implemented yet — see docs/document_lifecycle.md.

        total = await self.db.scalar(
            select(func.count()).select_from(Document).where(*conditions)
        )

        result = await self.db.execute(
            select(Document)
            .where(*conditions)
            .order_by(Document.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        documents = result.scalars().all()

        return PagedResponse.build(
            items=[DocumentResponse.model_validate(d) for d in documents],
            total=total or 0,
            params=page,
        )
