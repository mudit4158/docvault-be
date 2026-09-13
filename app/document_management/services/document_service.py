"""Document lifecycle: upload, list, detail, rename, download, trash, restore, purge.

Specs: docs/document_lifecycle.md, docs/download_and_compression.md,
docs/sharing_and_access.md. Invariants enforced here:

  - Size is checked before type, and both before quota — an oversized or
    rejected file never consumes quota.
  - Files are encrypted before they reach storage.
  - Soft delete only. Trashing revokes every share; restoring does NOT bring
    shares back (decision D2).
  - Rename keeps the extension the file was uploaded with.
  - Every read path filters out soft-deleted documents.
  - Access-log entries are written after permission checks, in the same
    transaction as the action.
"""

import uuid
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.document_management.models.doc_tag import DocTag
from app.document_management.models.document import Document
from app.document_management.models.tag import Tag
from app.document_management.schemas.common import DocumentType, PersonSummary
from app.document_management.schemas.document import (
    DocumentDetail,
    DocumentListFilters,
    DocumentSummary,
    TrashItem,
    UpdateDocumentRequest,
)
from app.document_management.services.access_log_service import AccessLogService
from app.document_management.services.access_service import AccessService
from app.document_management.services.file_inspection import (
    MIME_BY_EXTENSION,
    UnsupportedFileError,
    inspect_file,
)
from app.document_management.services.share_service import ShareService
from app.document_management.services.tag_service import TagService
from app.shared.clock import ensure_utc, utcnow
from app.shared.encryption import decrypt, encrypt
from app.shared.exceptions import (
    FileTooLargeError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    UnsupportedMediaTypeError,
)
from app.shared.pagination import PagedResponse, PageParams
from app.shared.storage.interface import get_storage
from app.user_management.models.account import Account
from app.user_management.services.quota_service import UploadQuotaService


def storage_key_for(document_id: uuid.UUID) -> str:
    return f"documents/{document_id}/original"


def display_name(requested: str, extension: str) -> str:
    """The name to store: the user's text, minus any extension they typed,
    plus the file's real extension.

    Only a suffix that looks like a file extension (1–5 characters, at least
    one letter) is stripped: "My Aadhaar.exe" becomes "My Aadhaar.pdf", but
    "Policy v1.2" keeps its ".2" rather than becoming "Policy v1.pdf".
    """
    base = PurePosixPath(requested.replace("\\", "/")).name.strip()
    suffix = PurePosixPath(base).suffix.lower()
    if suffix and (suffix in MIME_BY_EXTENSION or _looks_like_extension(suffix)):
        base = base[: -len(suffix)]
    stem = " ".join(base.split())[:200] or "Document"
    return f"{stem}{extension}"


def _looks_like_extension(suffix: str) -> bool:
    body = suffix[1:]
    return 1 <= len(body) <= 5 and body.isalnum() and any(c.isalpha() for c in body)


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):g} MB"


def _escape_like(value: str) -> str:
    """So a search for "%" matches a literal percent sign, not every row."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.access = AccessService(db)
        self.log = AccessLogService(db)

    # --- upload -----------------------------------------------------------

    async def upload(
        self,
        owner_id: uuid.UUID,
        filename: str,
        data: bytes,
        doc_type: DocumentType,
        requested_name: str | None,
    ) -> DocumentSummary:
        cap = settings.max_upload_size_bytes
        if len(data) > cap:
            raise FileTooLargeError(f"This file is larger than the {_megabytes(cap)} limit.")

        try:
            inspected = inspect_file(filename, data)
        except UnsupportedFileError as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc

        await UploadQuotaService(self.db).consume(owner_id)

        document_id = uuid.uuid4()
        key = storage_key_for(document_id)
        # If a later step fails the transaction rolls back but this file stays
        # behind as an orphan; a periodic sweep removes those (tracker #41).
        await get_storage().put(key, encrypt(data))

        now = utcnow()
        document = Document(
            id=document_id,
            owner_id=owner_id,
            name=display_name(requested_name or filename, inspected.extension),
            original_extension=inspected.extension,
            mime_type=inspected.mime_type,
            doc_type=doc_type,
            size_bytes=len(data),
            page_count=inspected.page_count,
            storage_key=key,
            created_at=now,
            updated_at=now,
        )
        self.db.add(document)
        await self.db.flush()

        await self.log.record(document.id, owner_id, "upload")
        await self.db.flush()
        return (await self._summaries([document]))[0]

    # --- reads ------------------------------------------------------------

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        filters: DocumentListFilters,
        page: PageParams,
    ) -> PagedResponse[DocumentSummary]:
        """The caller's active documents, newest first. Serves list and grid
        views alike — grid is a client-side layout of the same rows."""
        conditions = [Document.owner_id == owner_id, Document.deleted_at.is_(None)]

        if filters.q and filters.q.strip():
            pattern = f"%{_escape_like(filters.q.strip())}%"
            tag_match = exists(
                select(DocTag.document_id)
                .join(Tag, Tag.id == DocTag.tag_id)
                .where(DocTag.document_id == Document.id, Tag.label.ilike(pattern, escape="\\"))
            )
            conditions.append(or_(Document.name.ilike(pattern, escape="\\"), tag_match))

        if filters.doc_type:
            conditions.append(Document.doc_type == filters.doc_type)

        if filters.tag and filters.tag.strip():
            conditions.append(
                exists(
                    select(DocTag.document_id)
                    .join(Tag, Tag.id == DocTag.tag_id)
                    .where(
                        DocTag.document_id == Document.id,
                        func.lower(Tag.label) == " ".join(filters.tag.split()).lower(),
                    )
                )
            )

        total = await self.db.scalar(select(func.count()).select_from(Document).where(*conditions))
        documents = (
            await self.db.scalars(
                select(Document)
                .where(*conditions)
                .order_by(Document.created_at.desc())
                .offset(page.offset)
                .limit(page.page_size)
            )
        ).all()

        return PagedResponse.build(
            items=await self._summaries(list(documents)),
            total=total or 0,
            params=page,
        )

    async def get_detail(self, document_id: uuid.UUID, account_id: uuid.UUID) -> DocumentDetail:
        document, permission = await self.access.require_access(document_id, account_id)
        owner = await self.db.get(Account, document.owner_id)
        is_owner = permission == "owner"

        return DocumentDetail(
            id=document.id,
            name=document.name,
            doc_type=document.doc_type,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            page_count=document.page_count,
            created_at=document.created_at,
            updated_at=document.updated_at,
            owner=PersonSummary(
                id=document.owner_id,
                display_name=owner.display_name if owner else "Unknown",
            ),
            my_permission=permission,
            tags=(await TagService(self.db).tags_for([document.id]))[document.id]
            if is_owner
            else [],
            shares=await ShareService(self.db).list_for_document(document.id)
            if is_owner
            else None,
        )

    # --- owner edits ------------------------------------------------------

    async def update(
        self, document_id: uuid.UUID, account_id: uuid.UUID, data: UpdateDocumentRequest
    ) -> DocumentDetail:
        document = await self.access.require_owner(document_id, account_id)

        if data.name is not None:
            new_name = display_name(data.name, document.original_extension)
            if new_name != document.name:
                document.name = new_name
                await self.log.record(document.id, account_id, "rename")

        if data.doc_type is not None:
            document.doc_type = data.doc_type

        document.updated_at = utcnow()
        await self.db.flush()
        return await self.get_detail(document_id, account_id)

    # --- download ---------------------------------------------------------

    async def download(
        self, document_id: uuid.UUID, account_id: uuid.UUID
    ) -> tuple[Document, bytes]:
        """Decrypted bytes for the owner or a member with download permission.

        A view-only member gets 403, never a silent fallback. The whole file is
        held in memory, which is fine at the 20 MB cap; if the cap is raised
        substantially this should stream instead.
        """
        document, permission = await self.access.require_access(document_id, account_id)
        if permission not in ("owner", "download"):
            raise ForbiddenError(
                "You can view this document, but downloading it hasn't been allowed."
            )
        if document.storage_key is None:
            raise GoneError("This document's file is no longer available.")

        data = decrypt(await get_storage().get(document.storage_key))
        await self.log.record(document.id, account_id, "download")
        await self.db.flush()
        return document, data

    # --- trash ------------------------------------------------------------

    async def soft_delete(self, document_id: uuid.UUID, account_id: uuid.UUID) -> None:
        document = await self.access.require_owner(document_id, account_id)

        now = utcnow()
        document.deleted_at = now
        document.updated_at = now
        # The document vanishes from every group at once.
        await ShareService(self.db).revoke_all_for_document(document.id, account_id)
        await self.log.record(document.id, account_id, "delete")
        await self.db.flush()

    async def list_trash(self, account_id: uuid.UUID) -> list[TrashItem]:
        documents = (
            await self.db.scalars(
                select(Document)
                .where(
                    Document.owner_id == account_id,
                    Document.deleted_at.is_not(None),
                    # Purged documents have no file left to restore.
                    Document.storage_key.is_not(None),
                )
                .order_by(Document.deleted_at.desc())
            )
        ).all()

        now = utcnow()
        items = []
        for document in documents:
            purge_at = self._purge_at(document)
            items.append(
                TrashItem(
                    id=document.id,
                    name=document.name,
                    doc_type=document.doc_type,
                    size_bytes=document.size_bytes,
                    deleted_at=ensure_utc(document.deleted_at),  # type: ignore[arg-type]
                    purge_at=purge_at,
                    restorable=now < purge_at,
                )
            )
        return items

    async def restore(self, document_id: uuid.UUID, account_id: uuid.UUID) -> DocumentSummary:
        document = await self.db.get(Document, document_id)
        if document is None or document.owner_id != account_id or document.deleted_at is None:
            raise NotFoundError("Document not found in trash")

        if document.storage_key is None or utcnow() >= self._purge_at(document):
            days = settings.soft_delete_retention_days
            raise GoneError(
                f"This document was permanently deleted after {days} days in the trash "
                "and can't be restored."
            )

        document.deleted_at = None
        document.updated_at = utcnow()
        # Shares revoked at deletion stay revoked (decision D2): silently
        # re-opening access is a surprise; the owner re-shares deliberately.
        await self.log.record(document.id, account_id, "restore")
        await self.db.flush()
        return (await self._summaries([document]))[0]

    async def purge_expired(self) -> int:
        """Permanently remove files that have sat in the trash past retention.

        Run on a schedule (scripts/purge_trash.py). The metadata row and every
        access-log entry are kept, the row stays flagged deleted (PRD §4.3).
        Idempotent: already-purged documents are skipped, and deleting a file
        that is already gone is not an error.
        """
        cutoff = utcnow() - timedelta(days=settings.soft_delete_retention_days)
        documents = (
            await self.db.scalars(
                select(Document).where(
                    Document.deleted_at.is_not(None),
                    Document.storage_key.is_not(None),
                    Document.deleted_at < cutoff,
                )
            )
        ).all()

        storage = get_storage()
        for document in documents:
            await storage.delete(document.storage_key)  # type: ignore[arg-type]
            document.storage_key = None
            document.thumbnail_url = None
        await self.db.flush()
        return len(documents)

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _purge_at(document: Document):  # type: ignore[no-untyped-def]
        return ensure_utc(document.deleted_at) + timedelta(  # type: ignore[arg-type]
            days=settings.soft_delete_retention_days
        )

    async def _summaries(self, documents: list[Document]) -> list[DocumentSummary]:
        ids = [d.id for d in documents]
        tags = await TagService(self.db).tags_for(ids)
        share_counts = await ShareService(self.db).active_share_counts(ids)
        return [
            DocumentSummary(
                id=d.id,
                name=d.name,
                doc_type=d.doc_type,
                mime_type=d.mime_type,
                size_bytes=d.size_bytes,
                page_count=d.page_count,
                created_at=d.created_at,
                tags=tags.get(d.id, []),
                share_count=share_counts.get(d.id, 0),
            )
            for d in documents
        ]
