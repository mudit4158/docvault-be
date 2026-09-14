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
| Scanned PDFs | ✅ Yes — via the normal upload endpoint; no scan-specific endpoint |
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
| [`docs/scan_to_pdf.md`](docs/scan_to_pdf.md) | Why scans reuse the upload endpoint; client-side size, memory and security requirements |

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
| List / search / filter (`GET /documents`) | ✅ Name or tag search, doc-type + tag filters, paging |
| Upload — size cap, magic-byte type check, quota, AES-256-GCM, store, log | ✅ `services/document_service.py`, `services/file_inspection.py` |
| Download (original) | ✅ 403 for view-only |
| Compression tiers | ⬜ Pending — `docs/download_and_compression.md` |
| In-app preview (screenshots blocked) | ⬜ Pending — tracker #63 |
| Rename, change type | ✅ Extension preserved server-side |
| Soft delete / restore / trash | ✅ Delete revokes all shares; restore does not bring them back (D2) |
| Hard-delete job | 🟡 `scripts/purge_trash.py` built; scheduling pending |
| Thumbnails | ⬜ Pending |
| Tags + suggestions | ✅ Owner-only; suggestions = defaults + caller's own labels |
| Share grants — grant, update, revoke, group documents | ✅ Owner must belong to the group |
| Access log read | ✅ |
| Access log CSV export | ⬜ Pending |
| Storage | ✅ GCS (`GCSStorage`, production) · ✅ Local disk (`LOCAL_STORAGE_PATH`, dev) |
| Scan-to-PDF | No backend work — scans upload through `POST /documents`. See `docs/scan_to_pdf.md` |

## Planned Route Surface

| Method | Path | Feature |
|---|---|---|
| `GET` | `/documents` | ✅ List, search, filter, paginate |
| `POST` | `/documents` | ✅ Upload (multipart: `file`, `doc_type`, optional `name`) |
| `GET` | `/documents/{id}` | ✅ Detail |
| `PATCH` | `/documents/{id}` | ✅ Rename, change type |
| `DELETE` | `/documents/{id}` | ✅ Soft delete |
| `POST` | `/documents/{id}/restore` | ✅ Restore from trash |
| `GET` | `/documents/trash` | ✅ Trash listing |
| `GET` | `/documents/{id}/download` | ✅ Original · ⬜ `?compression=` tiers pending |
| `GET` | `/documents/{id}/download/sizes` | ⬜ Computed size per tier |
| `POST` | `/documents/{id}/tags` | ✅ Add tag |
| `DELETE` | `/documents/{id}/tags/{tag_id}` | ✅ Remove tag |
| `GET` | `/tags` | ✅ Tag suggestions |
| `GET` `POST` | `/documents/{id}/shares` | ✅ List / create-or-update share grant |
| `DELETE` | `/documents/{id}/shares/{grant_id}` | ✅ Revoke grant |
| `GET` | `/groups/{id}/documents` | ✅ Documents shared into a group (members only) |
| `GET` | `/documents/{id}/access-log` | ✅ Audit trail (owner only) |
| `GET` | `/documents/{id}/access-log/export` | ⬜ CSV export — pending |

**There is deliberately no `/documents/scan`.** A scanned PDF is assembled on the device and uploaded through `POST /documents`, identical to a file from storage.

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
