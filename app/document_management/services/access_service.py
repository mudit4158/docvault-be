"""The single authority on who may do what with a document.

Every read, download and owner-only action goes through here. See
docs/sharing_and_access.md for the rules; the order below is load-bearing:

  1. A soft-deleted document is accessible to nobody through normal paths.
  2. The owner always has full access.
  3. Otherwise access comes from an ACTIVE grant to a group the caller is a
     member of — resolved by joining through Membership at query time, so
     joining or leaving a group changes access immediately.
  4. Several groups can grant the same document; the highest permission wins.

Not-found and no-access are the same 404, so a document's existence is never
revealed to someone who cannot see it. 403 is reserved for a caller who can
see the document but lacks the permission for this particular action.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.document import Document
from app.document_management.models.share_grant import ShareGrant
from app.document_management.schemas.common import MyPermission
from app.shared.exceptions import ForbiddenError, NotFoundError
from app.user_management.models.membership import Membership


class AccessService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_permission(
        self, document: Document, account_id: uuid.UUID
    ) -> MyPermission | None:
        if document.deleted_at is not None:
            return None
        if document.owner_id == account_id:
            return "owner"

        permissions = (
            await self.db.scalars(
                select(ShareGrant.permission)
                .join(Membership, Membership.group_id == ShareGrant.group_id)
                .where(
                    ShareGrant.document_id == document.id,
                    ShareGrant.revoked_at.is_(None),
                    Membership.user_id == account_id,
                )
            )
        ).all()

        if not permissions:
            return None
        return "download" if "download" in permissions else "view"

    async def require_access(
        self, document_id: uuid.UUID, account_id: uuid.UUID
    ) -> tuple[Document, MyPermission]:
        document = await self.db.get(Document, document_id)
        permission = (
            await self.resolve_permission(document, account_id) if document else None
        )
        if document is None or permission is None:
            raise NotFoundError("Document not found")
        return document, permission

    async def require_owner(self, document_id: uuid.UUID, account_id: uuid.UUID) -> Document:
        document, permission = await self.require_access(document_id, account_id)
        if permission != "owner":
            raise ForbiddenError("Only the document's owner can do that")
        return document
