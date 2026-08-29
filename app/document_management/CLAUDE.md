# document_management — Module Context

## Scope

Owns the **document lifecycle and everything that governs access to a document**. This is the largest module and the core of the product.

| Concern | Owned here? |
|---|---|
| Upload, storage, encryption at rest | ✅ Yes |
| Document metadata, type, rename | ✅ Yes |
| Tags | ✅ Yes |
| Soft delete, trash, restore, hard-delete job | ✅ Yes |
| Share grants (which group can see which doc) | ✅ Yes |
| Access log (audit trail) | ✅ Yes |
| Download + compression | ✅ Yes |
| Thumbnail generation | ✅ Yes |
| Scan-to-PDF save endpoint | ✅ Yes |
| Who a user *is* | ❌ → `user_management` |
| Group membership / who is in a group | ❌ → `user_management` |
| Whether a paid feature is unlocked | ❌ → `billing` |

## Deep-Dive Docs

CLAUDE.md is the map. Implementation logic lives in `docs/`:

| Doc | Covers |
|---|---|
| [`docs/document_lifecycle.md`](docs/document_lifecycle.md) | Upload pipeline, states, soft delete, trash, hard-delete job, rename, thumbnails |
| [`docs/sharing_and_access.md`](docs/sharing_and_access.md) | ShareGrant semantics, the permission resolution algorithm, revocation |
| [`docs/access_log.md`](docs/access_log.md) | Event taxonomy, append-only rules, CSV export |
| [`docs/download_and_compression.md`](docs/download_and_compression.md) | Compression tiers, server-side size computation, streaming |
| [`docs/scan_to_pdf.md`](docs/scan_to_pdf.md) | Client/server split for the scan flow, single-save contract |

**Read the relevant doc before implementing.** Add a new `docs/*.md` per feature area rather than growing this file.

## Entities

| Model | File | Notes |
|---|---|---|
| `Document` | `models/document.py` | The vault is **flat** — no folder/parent field |
| `Tag` | `models/tag.py` | Label catalogue |
| `DocTag` | `models/tag.py` | Composite PK `(document_id, tag_id)` |
| `ShareGrant` | `models/share_grant.py` | Per-**group**, never per-user |
| `AccessLog` | `models/access_log.py` | Append-only. Never UPDATE or DELETE |

## Implementation Status

| Feature | Status |
|---|---|
| List documents (`GET /documents`) | ✅ **Sample flow** — copy this pattern |
| Upload | ⬜ Not built — `docs/document_lifecycle.md` |
| Preview / download | ⬜ Not built — `docs/download_and_compression.md` |
| Rename, change type | ⬜ Not built — `docs/document_lifecycle.md` |
| Soft delete / restore / trash | ⬜ Not built — `docs/document_lifecycle.md` |
| Hard-delete background job | ⬜ Not built — `docs/document_lifecycle.md` |
| Tags | ⬜ Not built |
| Share grants | ⬜ Not built — `docs/sharing_and_access.md` |
| Access log + CSV export | ⬜ Not built — `docs/access_log.md` |
| Scan-to-PDF save | ⬜ Not built — `docs/scan_to_pdf.md` |

## Planned Route Surface

| Method | Path | Feature |
|---|---|---|
| `GET` | `/documents` | ✅ Built — list, search, filter, sort, paginate |
| `POST` | `/documents` | Upload |
| `GET` | `/documents/{id}` | Detail |
| `PATCH` | `/documents/{id}` | Rename, change type |
| `DELETE` | `/documents/{id}` | Soft delete |
| `POST` | `/documents/{id}/restore` | Restore from trash |
| `GET` | `/documents/trash` | Trash listing |
| `GET` | `/documents/{id}/download` | Download, `?compression=none\|standard\|high` |
| `GET` | `/documents/{id}/download/sizes` | Computed size per tier |
| `POST` `DELETE` | `/documents/{id}/tags` | Add / remove tag |
| `GET` `POST` | `/documents/{id}/shares` | List / create share grant |
| `DELETE` | `/documents/{id}/shares/{grant_id}` | Revoke grant |
| `GET` | `/documents/{id}/access-log` | Audit trail (owner only) |
| `GET` | `/documents/{id}/access-log/export` | CSV export (owner only) |
| `POST` | `/documents/scan` | Save a completed scan session as one PDF document |

## Sample Flow — List Documents

`router/documents.py` → `services/document_service.py::DocumentService.list_for_owner`

The reference pattern for this module. Note the three things it demonstrates:

1. **Soft-delete filter is mandatory.** Every read query filters `deleted_at.is_(None)`.
2. **Ownership scoping.** Queries are always scoped to the caller.
3. **Paginated response.** Uses `PagedResponse.build` from `shared`.

```python
stmt = (
    select(Document)
    .where(Document.owner_id == owner_id, Document.deleted_at.is_(None))
    .order_by(Document.created_at.desc())
)
```

## Inter-Module Boundaries

- Imports `Account` and `UploadQuota` from `user_management` (ownership checks, quota decrement).
- Imports `Membership` from `user_management` to resolve whether a viewer is in a granted group.
- Calls `billing.services.feature_gate.FeatureGate` before any paid-feature action.
- **Never** imports from a router in another module — only models and services.
- `user_management.GroupService.delete()` calls into `ShareService.revoke_all_for_group()` here. Keep that entry point stable.

## Non-Negotiable Invariants

1. **Soft delete only.** Never `DELETE FROM documents`. Only the hard-delete job removes the stored *file*, and even then the metadata row is retained and stays flagged deleted (PRD §4.3).
2. **Every read filters `deleted_at IS NULL`** unless the endpoint is explicitly the trash listing.
3. **A soft-deleted document is invisible to groups** — permission resolution must check `deleted_at` before checking grants.
4. **Access log is append-only.** No UPDATE, no DELETE, ever. It outlives the file.
5. **Revoking a share grant emits an `AccessLog` `revoke` event** in the same transaction.
6. **Rename preserves the extension** from `Document.original_extension`, regardless of what the user types.
7. **Thumbnails are generated at upload/scan time**, never on demand.
8. **Compression sizes are computed server-side per file.** Never hardcode ratios.
9. **Size check precedes quota check** — see `user_management/docs/quota_rules.md`.
10. **The vault is flat.** Do not add a folder or parent-document field.
