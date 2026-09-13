import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.document_management.schemas.access_log import AccessLogPage
from app.document_management.schemas.common import DocumentType
from app.document_management.schemas.document import (
    DocumentDetail,
    DocumentListFilters,
    DocumentSummary,
    TrashItem,
    UpdateDocumentRequest,
)
from app.document_management.schemas.share import CreateShareRequest, ShareResponse
from app.document_management.schemas.tag import AddTagRequest, TagResponse
from app.document_management.services.access_log_service import AccessLogService
from app.document_management.services.document_service import DocumentService
from app.document_management.services.share_service import ShareService
from app.document_management.services.tag_service import TagService
from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.shared.pagination import PagedResponse, PageParams

# Every route here is authenticated.
router = APIRouter(prefix="/documents", tags=["documents"])


# --- vault -----------------------------------------------------------------


@router.get("", response_model=PagedResponse[DocumentSummary])
async def list_documents(
    q: str | None = Query(None, description="Matches file name and tag labels"),
    doc_type: DocumentType | None = Query(None),
    tag: str | None = Query(None, description="Exact tag label, case-insensitive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> PagedResponse[DocumentSummary]:
    """The caller's own documents. Serves both the list and grid views."""
    return await DocumentService(db).list_for_owner(
        owner_id=account_id,
        filters=DocumentListFilters(q=q, doc_type=doc_type, tag=tag),
        page=PageParams(page=page, page_size=page_size),
    )


@router.post("", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: DocumentType = Form("other"),
    name: str | None = Form(None, max_length=200),
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummary:
    """Upload one file. Scanned PDFs use this same endpoint.

    One file per request, so each gets its own progress and retry on the client.
    """
    # Read one byte past the cap: enough to know the file is too big without
    # holding an arbitrarily large body in memory. (The multipart parser has
    # already spooled the body to disk; a hard request-size limit belongs at
    # the reverse proxy — see docs/document_lifecycle.md.)
    data = await file.read(settings.max_upload_size_bytes + 1)
    return await DocumentService(db).upload(
        owner_id=account_id,
        filename=file.filename or "document",
        data=data,
        doc_type=doc_type,
        requested_name=name,
    )


# --- trash (declared before /{document_id} so "trash" is not taken as an id) --


@router.get("/trash", response_model=list[TrashItem])
async def list_trash(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[TrashItem]:
    return await DocumentService(db).list_trash(account_id)


# --- single document -------------------------------------------------------


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    """Owner, or a member of a group it is shared with. Everyone else: 404."""
    return await DocumentService(db).get_detail(document_id, account_id)


@router.patch("/{document_id}", response_model=DocumentDetail)
async def update_document(
    document_id: uuid.UUID,
    body: UpdateDocumentRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    """Rename or change type. Owner only. The file extension never changes."""
    return await DocumentService(db).update(document_id, account_id, body)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Move to trash. Owner only. Revokes every share immediately."""
    await DocumentService(db).soft_delete(document_id, account_id)


@router.post("/{document_id}/restore", response_model=DocumentSummary)
async def restore_document(
    document_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummary:
    """Restore from trash within the retention window. Shares are not restored."""
    return await DocumentService(db).restore(document_id, account_id)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The original file. Owner, or a member granted download permission."""
    document, data = await DocumentService(db).download(document_id, account_id)
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": _attachment(document.name),
            # Identity documents: never let a proxy or the device cache keep a copy.
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- tags ------------------------------------------------------------------


@router.post("/{document_id}/tags", response_model=list[TagResponse])
async def add_tag(
    document_id: uuid.UUID,
    body: AddTagRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[TagResponse]:
    """Add a tag. Owner only. Adding an existing tag is a no-op."""
    return await TagService(db).add(document_id, account_id, body.label)


@router.delete("/{document_id}/tags/{tag_id}", response_model=list[TagResponse])
async def remove_tag(
    document_id: uuid.UUID,
    tag_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[TagResponse]:
    return await TagService(db).remove(document_id, account_id, tag_id)


# --- sharing ---------------------------------------------------------------


@router.get("/{document_id}/shares", response_model=list[ShareResponse])
async def list_shares(
    document_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[ShareResponse]:
    return await ShareService(db).list_for_owner(document_id, account_id)


@router.post(
    "/{document_id}/shares", response_model=ShareResponse, status_code=status.HTTP_201_CREATED
)
async def share_document(
    document_id: uuid.UUID,
    body: CreateShareRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> ShareResponse:
    """Share with one of the owner's groups, or change an existing share's permission."""
    return await ShareService(db).grant(document_id, account_id, body.group_id, body.permission)


@router.delete("/{document_id}/shares/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    document_id: uuid.UUID,
    grant_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ShareService(db).revoke(document_id, grant_id, account_id)


# --- access log ------------------------------------------------------------


@router.get("/{document_id}/access-log", response_model=AccessLogPage)
async def access_log(
    document_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> AccessLogPage:
    """Who uploaded, shared, downloaded... Owner only. (CSV export: not built.)"""
    return await AccessLogService(db).list_for_owner(
        document_id, account_id, PageParams(page=page, page_size=page_size)
    )


def _attachment(filename: str) -> str:
    """Content-Disposition that survives non-ASCII names (RFC 6266 / 5987)."""
    fallback = filename.encode("ascii", "ignore").decode().replace('"', "") or "document"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
