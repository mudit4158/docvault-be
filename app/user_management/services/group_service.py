"""Groups, membership and invitations.

Full rules in app/user_management/docs/group_rules.md. The invariants this
service is responsible for:

  1. A group always has exactly one admin.
  2. The member cap is checked at INVITE time, and counts the admin.
  3. Deleting a group revokes its share grants but never deletes documents.
  4. The last admin cannot leave or be removed without transferring first.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.shared.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.user_management.models.account import Account
from app.user_management.models.group import Group
from app.user_management.models.invitation import Invitation
from app.user_management.models.membership import Membership
from app.user_management.schemas.account import AccountSummary
from app.user_management.schemas.group import (
    CreateGroupRequest,
    GroupResponse,
    InvitationResponse,
    MemberResponse,
    UpdateGroupRequest,
)


class GroupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- groups ----------------------------------------------------------

    async def create(self, caller_id: uuid.UUID, data: CreateGroupRequest) -> GroupResponse:
        """Create a group. The creator becomes its admin."""
        group = Group(name=data.name, description=data.description, created_by=caller_id)
        self.db.add(group)
        await self.db.flush()

        self.db.add(Membership(group_id=group.id, user_id=caller_id, role="admin"))
        await self.db.flush()

        return GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            created_at=group.created_at,
            my_role="admin",
            member_count=1,
        )

    async def list_for_member(self, caller_id: uuid.UUID) -> list[GroupResponse]:
        """Groups the caller belongs to, with their role and the member count."""
        member_count = (
            select(Membership.group_id, func.count().label("member_count"))
            .group_by(Membership.group_id)
            .subquery()
        )

        rows = await self.db.execute(
            select(Group, Membership.role, member_count.c.member_count)
            .join(Membership, Membership.group_id == Group.id)
            .join(member_count, member_count.c.group_id == Group.id)
            .where(Membership.user_id == caller_id)
            .order_by(Group.created_at.desc())
        )

        return [
            GroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                created_at=group.created_at,
                my_role=role,
                member_count=count,
            )
            for group, role, count in rows.all()
        ]

    async def get(self, group_id: uuid.UUID, caller_id: uuid.UUID) -> GroupResponse:
        group = await self._require_group(group_id)
        membership = await self._require_membership(group_id, caller_id)

        return GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            created_at=group.created_at,
            my_role=membership.role,
            member_count=await self._member_count(group_id),
        )

    async def update(
        self, group_id: uuid.UUID, caller_id: uuid.UUID, data: UpdateGroupRequest
    ) -> GroupResponse:
        group = await self._require_group(group_id)
        await self._require_admin(group_id, caller_id)

        if data.name is not None:
            group.name = data.name
        if data.description is not None:
            group.description = data.description
        await self.db.flush()

        return await self.get(group_id, caller_id)

    async def delete(self, group_id: uuid.UUID, caller_id: uuid.UUID) -> None:
        """Delete a group. Admin only.

        Every share into the group is revoked first, each with a "revoke"
        access-log entry. The documents themselves are NOT deleted — they stay
        in their owners' vaults (engineering handoff §2).
        """
        group = await self._require_group(group_id)
        await self._require_admin(group_id, caller_id)

        await self._revoke_group_shares(group_id, caller_id)
        # Memberships and invitations cascade via their FKs.
        await self.db.delete(group)
        await self.db.flush()

    async def _revoke_group_shares(self, group_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        # Function-local import: document_management depends on this module, so
        # a module-level import here would be circular.
        from app.document_management.services.share_service import ShareService

        await ShareService(self.db).revoke_all_for_group(group_id, actor_id)

    # --- members ---------------------------------------------------------

    async def list_members(
        self, group_id: uuid.UUID, caller_id: uuid.UUID
    ) -> list[MemberResponse]:
        await self._require_group(group_id)
        await self._require_membership(group_id, caller_id)

        rows = await self.db.execute(
            select(Membership, Account)
            .join(Account, Account.id == Membership.user_id)
            .where(Membership.group_id == group_id)
            .order_by(Membership.joined_at)
        )

        return [
            MemberResponse(
                account=AccountSummary.model_validate(account),
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for membership, account in rows.all()
        ]

    async def remove_member(
        self, group_id: uuid.UUID, target_id: uuid.UUID, caller_id: uuid.UUID
    ) -> None:
        """Remove a member. Admin only.

        The admin cannot remove themselves — that would leave the group with no
        admin. They transfer the role first, or delete the group.

        Removing a member does not revoke documents they already downloaded;
        that is out of scope for v1 (handoff §5, open question Q5).
        """
        await self._require_group(group_id)
        await self._require_admin(group_id, caller_id)

        if target_id == caller_id:
            raise ConflictError(
                "An admin cannot remove themselves — transfer admin rights first, "
                "or delete the group"
            )

        membership = await self._require_membership(group_id, target_id)
        await self.db.delete(membership)
        await self.db.flush()

    async def leave(self, group_id: uuid.UUID, caller_id: uuid.UUID) -> None:
        """Leave a group.

        Two guarded cases:
          - Sole admin with other members still present -> must transfer first,
            otherwise the group is left unadministrable.
          - Last member -> the group is deleted, since an empty group is
            unreachable by anyone.
        """
        await self._require_group(group_id)
        membership = await self._require_membership(group_id, caller_id)

        total = await self._member_count(group_id)

        if membership.role == "admin" and total > 1:
            raise ConflictError(
                "Transfer admin rights to another member before leaving this group"
            )

        await self.db.delete(membership)

        if total == 1:
            # Last member leaving deletes the group — same share cascade as delete().
            group = await self._require_group(group_id)
            await self._revoke_group_shares(group_id, caller_id)
            await self.db.delete(group)

        await self.db.flush()

    async def transfer_admin(
        self, group_id: uuid.UUID, new_admin_id: uuid.UUID, caller_id: uuid.UUID
    ) -> None:
        """Hand the admin role to another member.

        Both updates happen in one transaction so the group is never left with
        two admins or none.
        """
        await self._require_group(group_id)
        caller_membership = await self._require_admin(group_id, caller_id)

        if new_admin_id == caller_id:
            raise ConflictError("You are already the admin of this group")

        target_membership = await self._require_membership(group_id, new_admin_id)

        target_membership.role = "admin"
        caller_membership.role = "member"
        await self.db.flush()

    # --- invitations -----------------------------------------------------

    async def invite(
        self, group_id: uuid.UUID, phone: str, caller_id: uuid.UUID
    ) -> InvitationResponse:
        """Invite an existing DocVault user to the group. Admin only.

        The member cap is enforced HERE rather than at accept time, so the
        group cannot be over-subscribed by a batch of outstanding invitations
        all being accepted at once.
        """
        group = await self._require_group(group_id)
        await self._require_admin(group_id, caller_id)

        invitee = await self.db.scalar(select(Account).where(Account.phone == phone))
        if invitee is None:
            # Group invites reach existing users only. Inviting someone to the
            # platform is tracked as future scope.
            #
            # The wording says what the admin should DO about it, not just that
            # a lookup failed — "not found" reads like the app is broken.
            raise NotFoundError(
                f"{phone} does not have an active DocVault account. "
                "Ask them to sign up first, then invite them again."
            )

        if await self._membership_or_none(group_id, invitee.id) is not None:
            raise ConflictError("This person is already a member of the group")

        existing = await self.db.scalar(
            select(Invitation).where(
                Invitation.group_id == group_id,
                Invitation.invited_user_id == invitee.id,
            )
        )
        if existing is not None and existing.status == "pending":
            raise ConflictError("This person already has a pending invitation")

        cap = settings.group_member_cap
        # The cap counts the admin: handoff screen 18 shows "5 of 20 members"
        # listing the admin plus four members.
        if await self._member_count(group_id) >= cap:
            raise ConflictError(f"This group has reached its limit of {cap} members")

        if existing is not None:
            # A previously declined invitation is re-opened rather than
            # duplicated — the unique constraint on (group, user) forbids a
            # second row anyway.
            existing.status = "pending"
            existing.invited_by = caller_id
            invitation = existing
        else:
            invitation = Invitation(
                group_id=group_id,
                invited_user_id=invitee.id,
                invited_by=caller_id,
                status="pending",
            )
            self.db.add(invitation)

        await self.db.flush()

        caller = await self.db.get(Account, caller_id)
        return InvitationResponse(
            id=invitation.id,
            group_id=group_id,
            group_name=group.name,
            invited_by=AccountSummary.model_validate(caller) if caller else None,
            status=invitation.status,
            created_at=invitation.created_at,
        )

    async def list_my_invitations(
        self,
        caller_id: uuid.UUID,
        statuses: Sequence[str] | None = None,
    ) -> list[InvitationResponse]:
        """Invitations addressed to the caller.

        Defaults to pending + declined. Accepted ones are deliberately excluded:
        an accepted invitation is already represented by the group membership,
        so listing it again shows the same fact twice.

        The pending subset drives the badge count on the Groups tab
        (handoff §3.4); declined ones let the invitee find something they
        dismissed by accident.
        """
        wanted = list(statuses) if statuses else ["pending", "declined"]

        inviter = Account.__table__.alias("inviter")

        rows = await self.db.execute(
            select(Invitation, Group, inviter)
            .join(Group, Group.id == Invitation.group_id)
            .outerjoin(inviter, inviter.c.id == Invitation.invited_by)
            .where(
                Invitation.invited_user_id == caller_id,
                Invitation.status.in_(wanted),
            )
            .order_by(Invitation.created_at.desc())
        )

        result: list[InvitationResponse] = []
        for row in rows.all():
            invitation, group = row[0], row[1]
            inviter_id, inviter_phone, inviter_name = row[2], row[3], row[4]
            result.append(
                InvitationResponse(
                    id=invitation.id,
                    group_id=group.id,
                    group_name=group.name,
                    invited_by=(
                        AccountSummary(
                            id=inviter_id, phone=inviter_phone, display_name=inviter_name
                        )
                        if inviter_id is not None
                        else None
                    ),
                    status=invitation.status,
                    created_at=invitation.created_at,
                )
            )
        return result

    async def accept_invitation(self, invitation_id: uuid.UUID, caller_id: uuid.UUID) -> None:
        """Accept an invitation and join the group.

        The cap is re-checked here: invitations issued while there was room may
        be accepted after the group has since filled up.
        """
        invitation = await self._require_own_invitation(invitation_id, caller_id)

        if invitation.status == "accepted":
            return  # idempotent — already a member

        if invitation.status == "declined":
            raise ConflictError("This invitation has already been declined")

        cap = settings.group_member_cap
        if await self._member_count(invitation.group_id) >= cap:
            raise ConflictError(f"This group has reached its limit of {cap} members")

        invitation.status = "accepted"
        self.db.add(
            Membership(group_id=invitation.group_id, user_id=caller_id, role="member")
        )
        await self.db.flush()

    async def decline_invitation(self, invitation_id: uuid.UUID, caller_id: uuid.UUID) -> None:
        invitation = await self._require_own_invitation(invitation_id, caller_id)

        if invitation.status == "accepted":
            raise ConflictError("This invitation has already been accepted")

        invitation.status = "declined"
        await self.db.flush()

    # --- helpers ---------------------------------------------------------

    async def _require_group(self, group_id: uuid.UUID) -> Group:
        group = await self.db.get(Group, group_id)
        if group is None:
            raise NotFoundError("Group not found")
        return group

    async def _membership_or_none(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership | None:
        return await self.db.get(Membership, {"group_id": group_id, "user_id": user_id})

    async def _require_membership(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership:
        membership = await self._membership_or_none(group_id, user_id)
        if membership is None:
            # Deliberately 404, not 403: a non-member must not be able to tell
            # an existing group they cannot see from one that does not exist.
            raise NotFoundError("Group not found")
        return membership

    async def _require_admin(self, group_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
        membership = await self._require_membership(group_id, user_id)
        if membership.role != "admin":
            raise ForbiddenError("Only the group admin can perform this action")
        return membership

    async def _member_count(self, group_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.group_id == group_id)
            )
        ) or 0

    async def _require_own_invitation(
        self, invitation_id: uuid.UUID, caller_id: uuid.UUID
    ) -> Invitation:
        invitation = await self.db.get(Invitation, invitation_id)
        # Same 404 for "no such invitation" and "someone else's invitation":
        # the caller must not learn that an invitation they cannot act on exists.
        if invitation is None or invitation.invited_user_id != caller_id:
            raise NotFoundError("Invitation not found")
        return invitation
