# Access Log — Implementation Detail

Source: PRD §4.8. UI reference: prototype screen 19.

## Contract

The access log is **append-only**. There is no update path and no delete path — not for users, not for admins, not for the hard-delete job.

> "Every view and download is recorded with actor and timestamp. The log outlives the file." — screen 19

Consequences:
- No `UPDATE access_logs` anywhere in the codebase.
- No `DELETE FROM access_logs` anywhere in the codebase.
- The hard-delete job purges the file and nulls `storage_key`, but **leaves every log row intact** (PRD §4.3).
- Log rows survive their document's metadata being flagged deleted.

Anyone adding a mutation path to this table is breaking the product's audit guarantee. Treat it as immutable.

## Event Taxonomy

```python
AccessEvent = Literal[
    "upload",    # document created (upload or scan save)
    "view",      # preview opened
    "download",  # file downloaded, compressed or not
    "share",     # ShareGrant created or its permission changed
    "revoke",    # ShareGrant revoked (manual, or cascaded from group/doc delete)
    "delete",    # soft delete
    "restore",   # restored from trash
    "rename",    # name changed
]
```

Add new event types by extending this list — never by overloading an existing one.

## Row Shape

| Column | Meaning |
|---|---|
| `id` | PK |
| `document_id` | FK → documents. **No cascade delete** — the row outlives the document |
| `actor_id` | FK → accounts. The account that performed the action |
| `event_type` | From the taxonomy above |
| `created_at` | UTC timestamp, server-generated |

`actor_id` is nullable only to survive account deletion. When an account is removed, `SET NULL` rather than losing the audit trail. The FK on `document_id` must **not** be `ON DELETE CASCADE`.

## Writing Entries

Log writes happen **in the same transaction** as the action they record. If the action rolls back, the log entry rolls back with it — the log must never claim something happened that did not.

```python
class AccessLogService:
    async def record(
        self,
        document_id: uuid.UUID,
        actor_id: uuid.UUID,
        event_type: AccessEvent,
    ) -> None:
        self.db.add(
            AccessLog(document_id=document_id, actor_id=actor_id, event_type=event_type)
        )
        # No commit — the caller's transaction owns this.
```

Never make this a background task or a fire-and-forget queue write. It is transactional by design.

### Where Each Event Is Emitted

| Event | Emitted by |
|---|---|
| `upload` | `DocumentService.upload`, `ScanService.save` |
| `view` | preview / detail endpoint, after the permission check passes |
| `download` | download endpoint, after the permission check passes |
| `share` | `ShareService.grant` |
| `revoke` | `ShareService.revoke`, `revoke_all_for_document`, `revoke_all_for_group` |
| `delete` | `DocumentService.soft_delete` |
| `restore` | `DocumentService.restore` |
| `rename` | `DocumentService.rename` |

Log **after** the permission check, not before. A rejected access attempt is not an access.

## Reading the Log

`GET /documents/{id}/access-log` — **owner only** (PRD §4.8, screen 19 header reads "OWNER ONLY").

A group member who can view a document cannot see its log. Enforce with an explicit ownership check, not `resolve_permission`:

```python
if document.owner_id != account_id:
    raise ForbiddenError("Only the document owner can view its access log")
```

Ordered newest-first, paginated. The screen also shows two summary counts in its header ("7 events · 2 downloads") — compute these as aggregates, do not fetch all rows to count them client-side.

## CSV Export

`GET /documents/{id}/access-log/export` — owner only (PRD §4.8).

Stream the response rather than building the whole file in memory:

```python
return StreamingResponse(
    _rows_as_csv(...),
    media_type="text/csv",
    headers={"Content-Disposition": f'attachment; filename="access-log-{document_id}.csv"'},
)
```

Columns: `timestamp,actor_id,actor_phone,event_type`.

Exporting the log is itself **not** a logged event — otherwise reading the log would grow the log.

## Retention

Log rows are retained indefinitely. There is no purge job.

**Open question (engineering handoff §5, item 4):** legal has not yet confirmed a retention period for audit data on identity documents. Until they do, retain everything. Do not add a purge job speculatively — deleting audit data is not reversible.
