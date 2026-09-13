import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.document_management.schemas.common import (
    DocumentType,
    MyPermission,
    PersonSummary,
)
from app.document_management.schemas.share import ShareResponse
from app.document_management.schemas.tag import TagResponse


class DocumentSummary(BaseModel):
    """A row in the owner's vault list."""

    id: uuid.UUID
    name: str
    doc_type: DocumentType
    mime_type: str
    size_bytes: int
    page_count: int | None
    created_at: datetime
    tags: list[TagResponse]
    # Active grants — drives the "1 group" / "Private" label (handoff §2).
    share_count: int


class DocumentDetail(BaseModel):
    id: uuid.UUID
    name: str
    doc_type: DocumentType
    mime_type: str
    size_bytes: int
    page_count: int | None
    created_at: datetime
    updated_at: datetime
    owner: PersonSummary
    my_permission: MyPermission
    # Owner-only. A group member sees neither the owner's private labels nor
    # which other groups the document is shared with.
    tags: list[TagResponse]
    shares: list[ShareResponse] | None


class UpdateDocumentRequest(BaseModel):
    """Rename and/or change type. Any extension typed in `name` is discarded;
    the document keeps the extension it was uploaded with."""

    name: str | None = Field(None, min_length=1, max_length=200, pattern=r"^[^/\\\x00]+$")
    doc_type: DocumentType | None = None


class TrashItem(BaseModel):
    id: uuid.UUID
    name: str
    doc_type: DocumentType
    size_bytes: int
    deleted_at: datetime
    # When the file will be permanently removed.
    purge_at: datetime
    restorable: bool


class DocumentListFilters(BaseModel):
    """Query filters for GET /documents.

    `q` matches filename and tag label only — no OCR/content search in MVP.
    """

    q: str | None = None
    doc_type: DocumentType | None = None
    tag: str | None = None
