import uuid
from datetime import datetime

from pydantic import BaseModel

from app.document_management.schemas.common import DocumentType, PersonSummary, SharePermission


class CreateShareRequest(BaseModel):
    group_id: uuid.UUID
    permission: SharePermission


class ShareResponse(BaseModel):
    """An active grant, as the document's owner sees it."""

    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    permission: SharePermission
    created_at: datetime


class GroupDocument(BaseModel):
    """A document shared into a group, as a member of that group sees it."""

    id: uuid.UUID
    name: str
    doc_type: DocumentType
    mime_type: str
    size_bytes: int
    page_count: int | None
    created_at: datetime
    owner: PersonSummary
    permission: SharePermission
    shared_at: datetime
