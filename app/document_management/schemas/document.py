import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DocumentType = Literal["aadhaar", "voter_id", "pan", "passport", "other"]


class DocumentResponse(BaseModel):
    id: uuid.UUID
    name: str
    doc_type: DocumentType
    mime_type: str
    size_bytes: int
    page_count: int | None
    thumbnail_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListFilters(BaseModel):
    """Query filters for GET /documents.

    `q` matches filename and tag label only — no OCR/content search in MVP.
    """

    q: str | None = None
    doc_type: DocumentType | None = None
    tag: str | None = None
