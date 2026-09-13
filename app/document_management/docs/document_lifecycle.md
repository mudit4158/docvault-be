# Document Lifecycle — Implementation Detail

Source: PRD §4.1 (Upload), §4.2 (Management), §4.3 (Deletion & Retention), §4.9 (Type), §4.10 (Tags).
UI reference: prototype screens 02–06, 09, 11.

## State Machine

```
        upload / scan
             │
             ▼
        ┌─────────┐   DELETE /documents/{id}    ┌──────────┐
        │ active  │ ─────────────────────────▶  │ trashed  │
        │         │ ◀───────────────────────── │          │
        └─────────┘   POST .../restore          └──────────┘
                                                      │
                                         hard-delete job after N days
                                                      ▼
                                                ┌──────────┐
                                                │  purged  │
                                                └──────────┘
                                            (file gone, row retained)
```

| State | `deleted_at` | `storage_key` | Visible in vault | Group-accessible |
|---|---|---|---|---|
| active | `NULL` | set | ✅ | ✅ (if granted) |
| trashed | set | set | ❌ (trash view only) | ❌ |
| purged | set | `NULL` | ❌ | ❌ |

There is no separate `status` column — state is derived from `deleted_at` and `storage_key`. Adding a status enum would let the two disagree.

## Upload Pipeline

```
POST /documents  (multipart)
  │
  ├─ 1. Validate MIME type       → 415 if not in ALLOWED_MIME_TYPES
  ├─ 2. Validate size            → 413 if > settings.max_upload_size_bytes
  ├─ 3. Lock + roll quota row    → SELECT ... FOR UPDATE
  ├─ 4. Check quota              → 429 if files_used_today >= cap_files
  │      ── transaction begins ──
  ├─ 5. Encrypt bytes            → shared.encryption
  ├─ 6. storage.put(key, bytes)  → shared.storage
  ├─ 7. Generate thumbnail       → store, set thumbnail_url
  ├─ 8. INSERT Document
  ├─ 9. INCREMENT files_used_today
  ├─10. INSERT AccessLog(event_type="upload")
  │      ── commit ──
  └─ 201 { document }
```

Steps 1–2 run **before** any quota mutation — an oversized file must never consume quota (PRD screen 12). See `user_management/docs/quota_rules.md` for the full rationale.

If step 6 succeeds but a later step fails, the transaction rolls back but the **file is orphaned in storage**. Handle this with a periodic orphan sweep that deletes storage keys with no matching `Document` row — do not try to compensate inline.

### Allowed MIME Types (PRD §4.1)

```python
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/csv",
    "image/jpeg",
    "image/png",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
```

Validate the **sniffed** content type, not the client-supplied `Content-Type` header. A client can lie about the header.

### Page Count

For PDFs, the server reads `page_count` from the file itself. Never accept it from the request — a client-supplied count is untrusted and would drift from the real file.

### Scanned Documents Use This Same Pipeline

There is no separate scan endpoint. The app assembles a scanned PDF on the device and uploads it here like any other file; the server neither knows nor needs to know it was scanned. See `scan_to_pdf.md`.

### Multi-File Upload

The client uploads files **one request per file**, not one request with N files. Each file gets its own progress bar and its own retry (screen 11). The server does not need a batch endpoint.

Each file is an independent quota decrement. If file 3 of 5 fails, files 1–2 stay uploaded and consume 2 quota units; file 3 consumes none.

## Document Type

Single-valued, set at upload, changeable later (PRD §4.9).

```python
DocumentType = Literal["aadhaar", "voter_id", "pan", "passport", "other"]
```

Stored as a string enum column on `Document`. Exactly one per document — this is **not** a tag. Auto-detection via OCR is explicitly out of scope for MVP (PRD §6).

## Tags

Many-to-many, via `DocTag` (PRD §4.10). Seeded labels: Favourites, Identity Proof, Medical, Home. Users can apply multiple tags to one document.

Tags are a shared catalogue, not per-user rows. When a user "adds a tag", resolve-or-create the `Tag` by label, then insert the `DocTag` join. Deleting a `DocTag` never deletes the `Tag`.

## Rename

Screen 09 — inline edit. **The extension is preserved server-side regardless of what the user types.**

```python
def apply_rename(document: Document, user_input: str) -> str:
    stem = Path(user_input).stem          # strip whatever extension they typed
    return f"{stem}{document.original_extension}"
```

`original_extension` is captured at upload and never changes. This is why it is a separate column rather than being parsed out of `name` on demand.

## Soft Delete

`DELETE /documents/{id}` (PRD §4.3):

```
1. Verify caller owns the document      → 403 otherwise
2. SET deleted_at = now()
3. Revoke all active ShareGrants for the document
4. INSERT AccessLog(event_type="delete")
```

The document immediately disappears from the owner's vault and from every group. The file stays in storage for the retention window.

The client shows a 4-second undo snackbar before issuing the request (screen behaviour, engineering handoff §4) — the server sees either a delete or nothing. There is no server-side undo buffer.

## Restore

`POST /documents/{id}/restore` — allowed while `deleted_at + retention_days > now()`.

```
1. Verify ownership
2. Verify still within the retention window  → 410 Gone if purged
3. SET deleted_at = NULL
4. INSERT AccessLog(event_type="restore")
```

**Open question (PRD §10):** does restoring re-establish the ShareGrants that were revoked on delete? Current decision: **no** — grants stay revoked and the owner re-shares manually. Revocation is a security-relevant action and silently reversing it is surprising. Revisit if product disagrees.

## Hard-Delete Job

Runs daily. Retention is `settings.soft_delete_retention_days` (default 10).

```sql
SELECT id, storage_key FROM documents
WHERE deleted_at IS NOT NULL
  AND storage_key IS NOT NULL
  AND deleted_at < now() - INTERVAL 'N days';
```

For each row:
```
1. storage.delete(storage_key)
2. storage.delete(thumbnail_key)
3. SET storage_key = NULL, thumbnail_url = NULL
4. Leave the row in place — metadata is retained, still flagged deleted (PRD §4.3)
5. Leave the AccessLog rows untouched — the log outlives the file (PRD §4.3)
```

The job must be **idempotent**. Storage delete on a missing key is a no-op, not an error.

Retention is per-account once `billing` ships (a paid plan can extend it), so read the effective retention from the account's `PlanLimit` rather than from global config once that lands.

## Listing, Search, Filter, Sort

`GET /documents` (PRD §4.2) — one endpoint serves both list and grid views. Grid is a **client-side** layout toggle over the same payload (engineering handoff §3.1); do not build a second endpoint.

| Param | Behaviour |
|---|---|
| `q` | Case-insensitive match on **filename and tag label only**. No OCR/content search in MVP (explicitly deferred). |
| `doc_type` | Exact match on the type enum |
| `tag` | Filter by tag label; joins through `DocTag` |
| `sort` | `created_at` desc by default |
| `page`, `page_size` | Via `shared.pagination.PageParams` |

Must stay performant at 500+ documents per user (PRD §5). Required indexes:

```
documents(owner_id, deleted_at)          -- the hot path for every list query
documents(owner_id, created_at DESC)     -- default sort
doc_tags(document_id)                    -- tag join
```

## Thumbnails

Generated **once, at upload/scan time** (engineering handoff §3.1). The detail screen renders a static thumbnail, not a live render.

- PDF → render page 1 to PNG
- Image → downscale
- Other formats → no thumbnail; `thumbnail_url` stays `NULL` and the client shows a type icon

Thumbnail generation failure must **not** fail the upload. Log it, leave `thumbnail_url` NULL, continue.

## Encryption at Rest

Every stored file is encrypted before it reaches the storage backend (PRD §5, screen 06 shows "Encrypted at rest · AES-256"). Encryption happens in `shared/encryption.py`, above the storage layer — so a future P2P backend inherits it without change.
