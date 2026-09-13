"""Sharing documents with groups. Rules in docs/sharing_and_access.md.

  - Grants are per GROUP, never per user.
  - Only the owner creates or revokes grants.
  - The owner can only share into a group they are a member of. A group id is
    not a secret, and letting anyone push a document into any group would let
    a stranger's group receive your files by mistake.
  - Revocation is soft (revoked_at) and always emits an access-log "revoke".
  - One ACTIVE grant per (document, group): re-sharing updates the permission
    in place; the database enforces it with a partial unique index.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_management.models.document import Document
from app.document_management.models.share_grant import ShareGrant
from app.document_management.schemas.common import PersonSummary, SharePermission
from app.document_management.schemas.share import GroupDocument, ShareResponse
from app.document_management.services.access_log_service import AccessLogService
from app.document_management.services.access_service import AccessService
from app.shared.clock import utcnow
from app.shared.exceptions import NotFoundError
from app.user_management.models.account import Account
from app.user_management.models.group import Group
from app.user_management.models.membership import Membership


class ShareService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = AccessLogService(db)

    # --- owner actions ----------------------------------------------------

    async def list_for_owner(
        self, document_id: uuid.UUID, account_id: uuid.UUID
    ) -> list[ShareResponse]:
        await AccessService(self.db).require_owner(document_id, account_id)
        return await self.list_for_document(document_id)

    async def grant(
        self,
        document_id: uuid.UUID,
        account_id: uuid.UUID,
        group_id: uuid.UUID,
        permission: SharePermission,
    ) -> ShareResponse:
        document = await AccessService(self.db).require_owner(document_id, account_id)

        group = await self.db.get(Group, group_id)
        membership = await self.db.get(Membership, {"group_id": group_id, "user_id": account_id})
        if group is None or membership is None:
            # Same 404 whether the group does not exist or the owner is not in
            # it — no probing for group ids.
            raise NotFoundError("Group not found")

        grant = await self.db.scalar(
            select(ShareGrant).where(
                ShareGrant.document_id == document.id,
                ShareGrant.group_id == group_id,
                ShareGrant.revoked_at.is_(None),
            )
        )

        if grant is None:
            grant = ShareGrant(
                id=uuid.uuid4(),
                document_id=document.id,
                group_id=group_id,
                permission=permission,
                created_at=utcnow(),
            )
            self.db.add(grant)
            await self.log.record(document.id, account_id, "share")
        elif grant.permission != permission:
            grant.permission = permission
            await self.log.record(document.id, account_id, "share")

        await self.db.flush()
        return ShareResponse(
            id=grant.id,
            group_id=group.id,
            group_name=group.name,
            permission=grant.permission,
            created_at=grant.created_at,
        )

    async def revoke(
        self, document_id: uuid.UUID, grant_id: uuid.UUID, account_id: uuid.UUID
    ) -> None:
        document = await AccessService(self.db).require_owner(document_id, account_id)

        grant = await self.db.get(ShareGrant, grant_id)
        if grant is None or grant.document_id != document.id or grant.revoked_at is not None:
            raise NotFoundError("Share not found")

        grant.revoked_at = utcnow()
        # Required, and in the same transaction (handoff §3.2): revocation is a
        # security event and the log is the only record that it happened.
        await self.log.record(document.id, account_id, "revoke")
        await self.db.flush()

    # --- cascades ---------------------------------------------------------

    async def revoke_all_for_document(
        self, document_id: uuid.UUID, actor_id: uuid.UUID | None
    ) -> int:
        """Revoke every active grant on a document — used when it is trashed."""
        grants = await self._active_grants(ShareGrant.document_id == document_id)
        now = utcnow()
        for grant in grants:
            grant.revoked_at = now
            await self.log.record(grant.document_id, actor_id, "revoke")
        await self.db.flush()
        return len(grants)

    async def revoke_all_for_group(self, group_id: uuid.UUID, actor_id: uuid.UUID | None) -> int:
        """Revoke every active grant into a group — used when the group is deleted.

        Stable cross-module entry point: user_management.GroupService calls it.
        Documents are never deleted; they stay in their owners' vaults.
        """
        grants = await self._active_grants(ShareGrant.group_id == group_id)
        now = utcnow()
        for grant in grants:
            grant.revoked_at = now
            await self.log.record(grant.document_id, actor_id, "revoke")
        await self.db.flush()
        return len(grants)

    # --- reads ------------------------------------------------------------

    async def list_for_document(self, document_id: uuid.UUID) -> list[ShareResponse]:
        rows = await self.db.execute(
            select(ShareGrant, Group.name)
            .join(Group, Group.id == ShareGrant.group_id)
            .where(ShareGrant.document_id == document_id, ShareGrant.revoked_at.is_(None))
            .order_by(ShareGrant.created_at)
        )
        return [
            ShareResponse(
                id=grant.id,
                group_id=grant.group_id,
                group_name=group_name,
                permission=grant.permission,
                created_at=grant.created_at,
            )
            for grant, group_name in rows.all()
        ]

    async def active_share_counts(
        self, document_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not document_ids:
            return {}
        rows = await self.db.execute(
            select(ShareGrant.document_id, func.count())
            .where(ShareGrant.document_id.in_(document_ids), ShareGrant.revoked_at.is_(None))
            .group_by(ShareGrant.document_id)
        )
        return {document_id: count for document_id, count in rows.all()}

    async def list_group_documents(
        self, group_id: uuid.UUID, caller_id: uuid.UUID
    ) -> list[GroupDocument]:
        """Documents shared into a group — the group's "Documents" tab (screen 18)."""
        membership = await self.db.get(Membership, {"group_id": group_id, "user_id": caller_id})
        if membership is None:
            raise NotFoundError("Group not found")

        rows = await self.db.execute(
            select(Document, ShareGrant, Account.display_name)
            .join(ShareGrant, ShareGrant.document_id == Document.id)
            .join(Account, Account.id == Document.owner_id)
            .where(
                ShareGrant.group_id == group_id,
                ShareGrant.revoked_at.is_(None),
                Document.deleted_at.is_(None),
            )
            .order_by(ShareGrant.created_at.desc())
        )
        return [
            GroupDocument(
                id=document.id,
                name=document.name,
                doc_type=document.doc_type,
                mime_type=document.mime_type,
                size_bytes=document.size_bytes,
                page_count=document.page_count,
                created_at=document.created_at,
                owner=PersonSummary(id=document.owner_id, display_name=owner_name),
                permission=grant.permission,
                shared_at=grant.created_at,
            )
            for document, grant, owner_name in rows.all()
        ]

    async def _active_grants(self, condition: object) -> list[ShareGrant]:
        return list(
            (
                await self.db.scalars(
                    select(ShareGrant).where(condition, ShareGrant.revoked_at.is_(None))
                )
            ).all()
        )
