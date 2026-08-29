# Group Rules — Implementation Detail

## Group Lifecycle

```
create → [active] → delete
                ↑
           transfer admin
```

A group has no "archived" or "suspended" state in MVP.

## Member Cap

- Default: 20 members (`settings.group_member_cap`), inclusive of the admin.
- Enforced at **invite time**: if `current_member_count >= cap`, raise `ConflictError("Group is at capacity")`.
- Check: `SELECT COUNT(*) FROM memberships WHERE group_id = ?` before inserting the invitation.

## Invitation Lifecycle

```
[pending] → accepted → (Membership row created)
          → declined → (row kept, status = "declined")
```

- Only the `invited_user_id` can accept or decline.
- Accepting an already-accepted invitation is a no-op (idempotent).
- A user can only have one pending invitation per group. Sending a second invite to the same user raises `ConflictError`.

## Admin Invariant

- Every group must have **exactly one** admin at all times.
- Admin transfer (`PATCH /groups/{id}/members/{uid}/role`):
  1. Verify caller is current admin.
  2. Set caller's `Membership.role = "member"`.
  3. Set target's `Membership.role = "admin"`.
  4. Both updates in one transaction.
- The creator of a group is automatically the admin (inserted as `role="admin"` alongside the `Group` row).

## Removing a Member

- Only the group admin can remove members.
- Admin cannot remove themselves — they must transfer admin first.
- Removing a member does NOT revoke documents they have already downloaded (out of scope for v1, per engineering handoff §4).
- Removing a member DOES immediately revoke their active share grants — this is handled in `document_management.services.share_service.revoke_for_member_removal(group_id, user_id)`.

## Leaving a Group

- Any member (including admin) can call `DELETE /groups/{id}/members/me`.
- If the leaving user is the only admin and there are other members → raise `ConflictError("Transfer admin before leaving")`.
- If the leaving user is the last member → delete the group.

## Deleting a Group

- Only the group admin can delete.
- Steps (all in one transaction):
  1. Revoke all `ShareGrant` rows where `group_id = ?` — call `share_service.revoke_all_for_group(group_id, db)`.
  2. Emit an `AccessLog` `revoke` event for each document that had active grants.
  3. Delete all `Membership` rows for the group.
  4. Delete all `Invitation` rows for the group.
  5. Delete the `Group` row.
- Documents themselves are **never deleted** — they return to the owner's vault silently.

## Cascade Rules Summary

| Action | ShareGrants | Documents | Memberships | Invitations |
|---|---|---|---|---|
| Group deleted | Revoked (set `revoked_at`) | Untouched | Deleted | Deleted |
| Member removed | No change to other members' grants | Untouched | Deleted | n/a |
| Member leaves | No change to other members' grants | Untouched | Deleted | n/a |
| Document soft-deleted | All grants for doc become inaccessible | `deleted_at` set | Untouched | Untouched |
