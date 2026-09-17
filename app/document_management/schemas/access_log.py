import uuid
from datetime import datetime

from pydantic import BaseModel

from app.document_management.schemas.common import PersonSummary


class AccessLogEntry(BaseModel):
    id: uuid.UUID
    event_type: str
    # None once the acting account has been deleted — the entry itself survives.
    actor: PersonSummary | None
    created_at: datetime


class AccessLogPage(BaseModel):
    items: list[AccessLogEntry]
    total: int
    page: int
    page_size: int
    has_next: bool
    # Summary counts shown in the log header (prototype screen 19).
    download_count: int
