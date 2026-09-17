# Sharing & Access Control — Implementation Detail

Source: PRD §4.7. UI reference: prototype screen 08.

## The Core Rule

**Share grants are per-group, never per-user.** There is no "share with a person" path. To share with someone, you share with a group they belong to.

This is the single most important structural fact in the module. It means:
- Adding a member to a group grants them access to everything shared with that group, retroactively.
- Removing a member revokes their access to everything shared with that group, immediately.
- Neither action touches any `ShareGrant` row.

## ShareGrant

| Column | Meaning |
|---|---|
| `id` | PK |
| `document_id` | FK → documents |
| `group_id` | FK → groups |
| `permission` | `"view"` or `"download"` |
| `created_at` | When granted |
| `revoked_at` | `NULL` while active; set on revoke |

A grant is **active** when `revoked_at IS NULL`. Revocation is a soft operation — the row is retained so the access log stays interpretable after the fact.

`permission` is a two-value ladder, not a set: `download` implies `view`. There is no download-without-view.

```python
Permission = Literal["view", "download"]
```

The detail screen's "1 group" / "Private" label is the **count of active grants**, computed at read time, not a stored column.

## Preview vs. Download

Two endpoints return the same decrypted bytes but gate and log differently:

- `GET /documents/{id}/download` — owner or `download` permission only. 403s a `view`-only member. Sets `Content-Disposition: attachment`. Logs `"download"`.
- `GET /documents/{id}/preview` — owner **or `view` or `download`** permission — anyone with any access at all. No `Content-Disposition` (rendered in-app, never saved to a file). Logs `"view"`, never `"download"`.

This is the entire reason the `view` permission tier exists: a `view`-only member can open the document in the app but has no path to a saved copy. Without `/preview`, `view` permission granted nothing to actually view with. See `app/user_management/../document_management/services/document_service.py`'s `preview()` and `download()` — they differ only in which permissions pass and which event they log; do not merge them into one method with a flag, since that would make it easy to accidentally let a flag default to the wrong (more permissive) side.

The Android client blocks screenshots while a preview is open (`SecureScreen()`, app-wide already) and never writes preview bytes to a user-visible file — see `docvault-fe`'s in-app viewer.

## Permission Resolution

The single authority for "can this account do this to this document". Every read, preview, and download path calls it. Implement it once, in `services/access_service.py`, and call it from everywhere:

```python
async def resolve_permission(
    self, document_id: uuid.UUID, account_id: uuid.UUID
) -> Literal["owner", "download", "view", None]:
    doc = await self._get(document_id)

    # 1. Soft-deleted documents are accessible to nobody, not even the owner's groups.
    if doc is None or doc.deleted_at is not None:
        return None

    # 2. Owner always has full access.
    if doc.owner_id == account_id:
        return "owner"

    # 3. Otherwise: is there an active grant to a group this account belongs to?
    stmt = (
        select(ShareGrant.permission)
        .join(Membership, Membership.group_id == ShareGrant.group_id)
        .where(
            ShareGrant.document_id == document_id,
            ShareGrant.revoked_at.is_(None),
            Membership.user_id == account_id,
        )
    )
    perms = (await self.db.execute(stmt)).scalars().all()
    if not perms:
        return None

    # 4. Multiple groups may grant the same doc. Take the highest permission.
    return "download" if "download" in perms else "view"
```

Four things this must always do, in this order:

1. **Check `deleted_at` first.** A trashed document is invisible to groups even though its grants may still exist (PRD §4.3).
2. **Owner bypass.** The owner never needs a grant for their own document.
3. **Join through `Membership`.** Access is derived from group membership at query time — never cached on the grant.
4. **Take the maximum** when a document is shared into several groups the user belongs to.

## Sharing a Document

`POST /documents/{id}/shares` — owner only.

```
1. Verify caller owns the document          → 403 otherwise
2. Verify the target group exists           → 404 otherwise
3. If an active grant already exists for (document, group):
     update its permission in place, do not insert a duplicate
   Else:
     INSERT ShareGrant
4. INSERT AccessLog(event_type="share")
```

Enforce one active grant per `(document_id, group_id)` pair. A partial unique index expresses this:

```sql
CREATE UNIQUE INDEX uq_active_grant
  ON share_grants (document_id, group_id)
  WHERE revoked_at IS NULL;
```

The owner **must be a member** of the group to share into it (tracker D22). A group the owner doesn't belong to returns 404 "Group not found" — the same answer as a group that doesn't exist, so group ids can't be probed. Without this, anyone holding a group id could push files at strangers.

Re-sharing into a group that already has an active grant updates that grant's permission in place; the partial unique index `uq_share_grants_active` guarantees at most one active grant per (document, group).

**What members see.** A member gets name, type, size, page count, owner and their own permission. Tags and the share list are **owner-only** (D23) — tags are the owner's private organisation, and the share list would reveal the owner's other groups.

## Revoking

`DELETE /documents/{id}/shares/{grant_id}` — owner only.

```
1. Verify ownership
2. SET revoked_at = now()      -- soft; never DELETE the row
3. INSERT AccessLog(event_type="revoke")   -- REQUIRED, same transaction
```

The access-log write is not optional (engineering handoff §3.2). Revocation is a security event and the log is the only record that it happened. There is no separate confirmation step in the UI — the toggle in the share sheet revokes immediately.

### Cascade Revocations

Three other operations revoke grants. All are soft revokes.

| Trigger | Scope | Entry point |
|---|---|---|
| Document soft-deleted | All grants for that document | `ShareService.revoke_all_for_document` |
| Group deleted | All grants to that group | `ShareService.revoke_all_for_group` |
| Owner removes a group from sharing | One grant | `ShareService.revoke` |

`revoke_all_for_group` is the entry point `user_management.GroupService.delete()` calls. **Keep its signature stable** — it is the one cross-module call into this service.

Group deletion revokes grants but **never deletes documents** (engineering handoff §2 callout). The documents return to their owners' vaults.

Removing a *member* from a group revokes nothing — their access disappears because the `Membership` join in `resolve_permission` no longer matches. Their already-downloaded local copies are out of scope for v1 (engineering handoff §5, open question).

## Enforcement at Download

Preview and download are separate permission levels:

```python
perm = await access_service.resolve_permission(doc_id, account_id)

if perm is None:
    raise ForbiddenError("You do not have access to this document")

# preview / view endpoint: any non-None perm is sufficient

# download endpoint:
if perm not in ("owner", "download"):
    raise ForbiddenError("Download access has not been granted")
```

A `view`-only member hitting the download endpoint gets a 403. Do not silently downgrade to a preview.

## What Is Deliberately Not Modelled

- **Per-user grants** — everything goes through groups.
- **Expiring grants** — no TTL on a share. Revocation is manual.
- **Re-share by members** — only the owner can create or revoke grants.
- **Group-level encryption keys** — post-MVP paid feature (PRD §7).
