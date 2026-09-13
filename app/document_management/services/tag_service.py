"""Tags (PRD §4.10). Owner-only, many per document.

Labels are matched case-insensitively with whitespace collapsed, so
"identity   proof" reuses "Identity Proof" instead of creating a near-duplicate.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.doc_tag import DocTag
from app.document_management.models.document import Document
from app.document_management.models.tag import Tag
from app.document_management.schemas.tag import TagResponse
from app.document_management.services.access_service import AccessService
from app.shared.clock import utcnow
from app.shared.exceptions import InvalidInputError

DEFAULT_TAGS = ("Favourites", "Identity Proof", "Medical", "Home")


def normalize_label(label: str) -> str:
    return " ".join(label.split())


class TagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def suggestions(self, account_id: uuid.UUID) -> list[str]:
        """The defaults plus labels THIS account has used.

        Tag rows are shared storage, but the list is never shared: someone
        else's labels can say a great deal about their documents.
        """
        used = (
            await self.db.scalars(
                select(Tag.label)
                .join(DocTag, DocTag.tag_id == Tag.id)
                .join(Document, Document.id == DocTag.document_id)
                .where(Document.owner_id == account_id)
                .distinct()
            )
        ).all()

        labels = {label.casefold(): label for label in DEFAULT_TAGS}
        for label in used:
            labels.setdefault(label.casefold(), label)
        return sorted(labels.values(), key=str.casefold)

    async def add(
        self, document_id: uuid.UUID, account_id: uuid.UUID, label: str
    ) -> list[TagResponse]:
        await AccessService(self.db).require_owner(document_id, account_id)

        clean = normalize_label(label)
        if not clean:
            raise InvalidInputError("A tag needs at least one visible character")

        tag = await self.db.scalar(select(Tag).where(func.lower(Tag.label) == clean.lower()))
        if tag is None:
            tag = Tag(id=uuid.uuid4(), label=clean, created_at=utcnow())
            self.db.add(tag)
            await self.db.flush()

        link = await self.db.get(DocTag, {"document_id": document_id, "tag_id": tag.id})
        if link is None:
            self.db.add(DocTag(document_id=document_id, tag_id=tag.id))
            await self.db.flush()

        return (await self.tags_for([document_id]))[document_id]

    async def remove(
        self, document_id: uuid.UUID, account_id: uuid.UUID, tag_id: uuid.UUID
    ) -> list[TagResponse]:
        await AccessService(self.db).require_owner(document_id, account_id)

        link = await self.db.get(DocTag, {"document_id": document_id, "tag_id": tag_id})
        if link is not None:
            # Only the join goes; the Tag row may be in use on other documents.
            await self.db.delete(link)
            await self.db.flush()

        return (await self.tags_for([document_id]))[document_id]

    async def tags_for(
        self, document_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[TagResponse]]:
        """Tags for many documents in one query, avoiding N+1 on list screens."""
        result: dict[uuid.UUID, list[TagResponse]] = {doc_id: [] for doc_id in document_ids}
        if not document_ids:
            return result

        rows = await self.db.execute(
            select(DocTag.document_id, Tag)
            .join(Tag, Tag.id == DocTag.tag_id)
            .where(DocTag.document_id.in_(document_ids))
            .order_by(Tag.label)
        )
        for document_id, tag in rows.all():
            result[document_id].append(TagResponse.model_validate(tag))
        return result
