import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.dependencies import get_current_account_id
from app.shared.db.session import get_db
from app.user_management.schemas.group import InvitationResponse
from app.user_management.services.group_service import GroupService

router = APIRouter(prefix="/invitations", tags=["invitations"])

# Invitations addressed TO the caller. Issuing an invitation lives on the group
# it belongs to: POST /groups/{id}/invite.


@router.get("", response_model=list[InvitationResponse])
async def list_my_invitations(
    status: Annotated[
        list[Literal["pending", "declined", "accepted"]] | None,
        Query(description="Repeatable. Defaults to pending + declined."),
    ] = None,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationResponse]:
    """Invitations for the caller.

    Defaults to pending + declined — an accepted invitation is already visible
    as a group membership. The pending subset drives the Groups tab badge.
    """
    return await GroupService(db).list_my_invitations(account_id, statuses=status)


@router.post("/{invitation_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invitation(
    invitation_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Accept an invitation and join the group."""
    await GroupService(db).accept_invitation(invitation_id, account_id)


@router.post("/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_invitation(
    invitation_id: uuid.UUID,
    account_id: uuid.UUID = Depends(get_current_account_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Decline an invitation."""
    await GroupService(db).decline_invitation(invitation_id, account_id)
