import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.user_management.schemas.group import (
    CreateGroupRequest,
    GroupResponse,
    InvitationResponse,
    InviteRequest,
    MemberResponse,
    TransferAdminRequest,
    UpdateGroupRequest,
)
from app.user_management.services.group_service import GroupService

router = APIRouter(prefix="/groups", tags=["groups"])

# Every route here is authenticated. There is no anonymous access to any group.


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[GroupResponse]:
    """Groups the caller belongs to."""
    return await GroupService(db).list_for_member(account_id)


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: CreateGroupRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Create a group. The caller becomes its admin."""
    return await GroupService(db).create(account_id, body)


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Group detail. Caller must be a member."""
    return await GroupService(db).get(group_id, account_id)


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    body: UpdateGroupRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Rename a group or change its description. Admin only."""
    return await GroupService(db).update(group_id, account_id, body)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a group. Admin only. Documents shared into it are NOT deleted."""
    await GroupService(db).delete(group_id, account_id)


# --- members --------------------------------------------------------------


@router.get("/{group_id}/members", response_model=list[MemberResponse])
async def list_members(
    group_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    """Members of a group. Caller must be a member."""
    return await GroupService(db).list_members(group_id, account_id)


@router.delete("/{group_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Leave a group. A sole admin must transfer the role first."""
    await GroupService(db).leave(group_id, account_id)


@router.delete("/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a member. Admin only."""
    await GroupService(db).remove_member(group_id, member_id, account_id)


@router.post("/{group_id}/transfer-admin", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_admin(
    group_id: uuid.UUID,
    body: TransferAdminRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hand admin rights to another member. The caller becomes a member."""
    await GroupService(db).transfer_admin(group_id, body.new_admin_id, account_id)


# --- invitations ----------------------------------------------------------


@router.post(
    "/{group_id}/invite",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    group_id: uuid.UUID,
    body: InviteRequest,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    """Invite an existing DocVault user by phone number. Admin only."""
    return await GroupService(db).invite(group_id, body.phone, account_id)
