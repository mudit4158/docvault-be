import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.schemas.document import (
    DocumentListFilters,
    DocumentResponse,
    DocumentType,
)
from app.document_management.services.document_service import DocumentService
from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.shared.pagination import PagedResponse, PageParams

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=PagedResponse[DocumentResponse])
async def list_documents(
    q: str | None = Query(None, description="Match on filename (and tags, once built)"),
    doc_type: DocumentType | None = Query(None),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> PagedResponse[DocumentResponse]:
    """List the caller's documents. Serves both the list and grid views."""
    return await DocumentService(db).list_for_owner(
        owner_id=account_id,
        filters=DocumentListFilters(q=q, doc_type=doc_type, tag=tag),
        page=PageParams(page=page, page_size=page_size),
    )
