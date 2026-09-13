import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.user_management.schemas.account import PHONE_PATTERN, AccountSummary

GroupRole = Literal["admin", "member"]
InvitationStatus = Literal["pending", "accepted", "declined"]


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    # The caller's own role in this group — drives which actions the client
    # offers (invite, remove, delete are admin-only).
    my_role: GroupRole
    member_count: int


class MemberResponse(BaseModel):
    account: AccountSummary
    role: GroupRole
    joined_at: datetime


class InviteRequest(BaseModel):
    """Invite by phone number.

    Group invitations only reach people who already have a DocVault account —
    inviting someone to the platform itself is tracked as future scope.
    """

    phone: str = Field(..., pattern=PHONE_PATTERN, examples=["+919876543210"])


class InvitationResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    invited_by: AccountSummary | None
    status: InvitationStatus
    created_at: datetime


class TransferAdminRequest(BaseModel):
    """Hand the admin role to an existing member.

    A group has exactly one admin, so this demotes the caller in the same
    transaction that promotes the target.
    """

    new_admin_id: uuid.UUID
