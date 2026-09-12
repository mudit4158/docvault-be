# Group Rules — Implementation Detail

**Status:** built, except the share-grant revocation on group delete (blocked on `document_management`).

## Group Lifecycle

```
create → [active] → delete
              ↑
        transfer admin
```

No archived or suspended state in MVP.

## The Admin Invariant

**Every group has exactly one admin at all times.** Three paths could break this; each is guarded:

| Path | Guard |
|---|---|
| Admin removes themselves | `409` — "transfer admin rights first, or delete the group" |
| Sole admin leaves while others remain | `409` — "transfer admin rights before leaving" |
| Admin transfer | Promotion and demotion in **one transaction**, so the group is never left with two admins or none |

The group creator is inserted as `role="admin"` in the same transaction as the `Group` row.

The last remaining member *can* leave — the group is deleted with them, since an empty group is unreachable by anyone.

## Member Cap

Default 20 (`settings.group_member_cap`), **inclusive of the admin**.

> Resolves PRD §10's open question. Handoff screen 18 shows "Sharma Family · 5 of 20 members" listing Mudit (admin) plus four members — so the admin counts.

Enforced in **two** places, deliberately:

1. **At invite time** — the primary check. Prevents over-subscribing a group with outstanding invitations.
2. **At accept time** — a re-check. An invitation issued while there was room may be accepted after the group has since filled up.

Checking only at accept would let an admin issue 50 invitations to a 20-seat group; checking only at invite would let all outstanding invitations land at once.

## Invitations

```
            invite
              ↓
         [pending] ──accept──▶ [accepted] → Membership created
              │
              └───decline──▶ [declined] ──re-invite──▶ [pending]
```

- **Existing users only.** Invite is by phone number; an unregistered number returns `404`. Inviting someone to the *platform* is future scope.
- **Only the invitee** can accept or decline. Anyone else gets `404`, not `403` — the caller must not learn that an invitation they cannot act on exists.
- **Accept is idempotent.** Re-accepting is a no-op, not a duplicate membership.
- **Accept after decline** → `409`. **Decline after accept** → `409`.
- **Re-inviting after a decline** reopens the same row rather than inserting a second one — the unique constraint on `(group_id, invited_user_id)` forbids a duplicate anyway.
- A pending invitation to someone already a member → `409`.

Pending invitations for the caller drive the Groups tab badge (handoff §3.4).

## Visibility — 404 over 403

Non-members get **404** on every group route, never 403. A 403 confirms the group exists; for a vault product that is a disclosure. `_require_membership` raises `NotFoundError("Group not found")` for both "no such group" and "not your group".

403 is reserved for the case where the caller *is* a member but lacks the role — an ordinary member attempting an admin action. There, existence is already known.

## Permissions

| Action | Admin | Member |
|---|---|---|
| View group, list members | ✅ | ✅ |
| Create group | — | anyone |
| Rename / edit description | ✅ | ❌ 403 |
| Invite | ✅ | ❌ 403 |
| Remove a member | ✅ | ❌ 403 |
| Transfer admin | ✅ | ❌ 403 |
| Delete group | ✅ | ❌ 403 |
| Leave | ✅ (after transfer) | ✅ |

## Removing a Member

Admin only, and the admin **cannot remove themselves**.

Removal does not revoke documents the member already downloaded — out of scope for v1 (handoff §5, open question Q5).

Once `document_management` exists, removal needs no share-grant change: access resolves through the `Membership` join at query time, so deleting the membership row removes access immediately.

## Deleting a Group

Admin only. Memberships and invitations cascade via their FKs.

> ⚠️ **Incomplete.** Deleting a group must also revoke every `ShareGrant` pointing at it, and must **never** delete the underlying documents (handoff §2). `ShareService` does not exist yet, so `GroupService.delete()` carries the call site as a comment:
>
> ```python
> from app.document_management.services.share_service import ShareService
> await ShareService(self.db).revoke_all_for_group(group_id)
> ```
>
> The import is function-local by design, to avoid a circular import at module load. Tracked as backend item #9.

## Cascade Summary

| Action | Memberships | Invitations | ShareGrants | Documents |
|---|---|---|---|---|
| Group deleted | Deleted (FK cascade) | Deleted (FK cascade) | ⬜ must be revoked | **Never deleted** |
| Member removed | That row deleted | Untouched | Untouched — access resolves via the join | Untouched |
| Member leaves | That row deleted | Untouched | Untouched | Untouched |
| Last member leaves | Deleted with the group | Deleted with the group | ⬜ must be revoked | **Never deleted** |

## Audit

Every group action is captured automatically — `groups`, `memberships` and `invitations` all declare `__audited__ = True`. An admin transfer produces **two** `memberships` UPDATE rows, one per side of the swap, each with its before/after role. See `shared/docs/audit_framework.md`.
