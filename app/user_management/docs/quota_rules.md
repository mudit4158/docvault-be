# Upload Quota Rules — Implementation Detail

Source: PRD §4.12 (Rate Limiting), §8.3 (Paid Limit Upgrades), §9 (Configurable Parameters).
UI reference: prototype screens 11 (upload) and 12 (blocked state).

## Model

`UploadQuota` — one row per account, PK is `account_id`.

| Column | Meaning |
|---|---|
| `account_id` | FK → `accounts.id`, cascade delete |
| `files_used_today` | Count of successful uploads in the current window |
| `period_reset_at` | UTC timestamp when the counter next resets |
| `cap_files` | This account's daily cap. Defaults to `settings.daily_upload_cap` (10); a paid plan may raise it |

`cap_files` is stored **per account**, not read from config at check time. This is deliberate — `billing` raises the cap by writing to this column, so a plan upgrade takes effect without a config change or restart.

## Reset Window

- The window is a rolling **24-hour** period anchored on `period_reset_at`.
- There is no cron job. The reset is **lazy**: on every quota check, if `now() >= period_reset_at`, set `files_used_today = 0` and push `period_reset_at` forward.

```python
def _roll_if_expired(quota: UploadQuota) -> None:
    now = datetime.now(timezone.utc)
    if now >= quota.period_reset_at:
        quota.files_used_today = 0
        quota.period_reset_at = now + timedelta(days=1)
```

Lazy reset means an inactive user's row is never touched, and there is no scheduled job to fail.

## Check Order — This Order Matters

The PRD (screen 12) states: *"Files over 20 MB are rejected before upload starts, so they never count against the daily cap."*

So `document_management` must run checks in exactly this order on upload:

```
1. Validate MIME type          → 415 if unsupported
2. Validate file size          → 413 FileTooLargeError if > settings.max_upload_size_bytes
3. Roll quota window if expired
4. Check files_used_today < cap_files → 429 QuotaExceededError if at cap
5. Write file to storage
6. INSERT Document row
7. INCREMENT files_used_today
```

Steps 4–7 must be in the same transaction. Consequences of this ordering:

- An **oversized** file is rejected at step 2 and never touches the counter.
- A **failed storage write** at step 5 rolls back, so the counter is not incremented — a failed upload does not consume quota. This answers PRD §10's open question *"Does a failed upload count towards the daily upload limit?"* → **No.**

## Concurrency

Two simultaneous uploads could both read `files_used_today = 9` against a cap of 10 and both succeed, letting 11 through.

Lock the row when checking:

```python
result = await db.execute(
    select(UploadQuota)
    .where(UploadQuota.account_id == account_id)
    .with_for_update()
)
```

`SELECT ... FOR UPDATE` serialises concurrent uploads for one account. Contention is negligible — the lock is per-account and held for the length of one upload transaction.

## Quota Status Response

`GET /me/quota` powers the "8/10 uploads" chip in the app header (screens 11, 12) and the blocked-state screen.

```json
{
  "files_used_today": 8,
  "cap_files": 10,
  "period_reset_at": "2026-08-30T00:00:00Z"
}
```

The client renders the reset time from `period_reset_at` — the server does not format it. Roll the window before responding so a stale row does not report a past reset time.

## What Quota Does NOT Block

Per screen 12: *"read access unaffected."* When the cap is reached, block **only new uploads**. These stay fully available:

- Listing, searching, previewing documents
- Downloading (with or without compression)
- Sharing and revoking share grants
- Group operations
- Restoring a soft-deleted document

Only `POST /documents` and the scan save endpoint return `429`.

## Paid Plan Overrides

`billing` raises limits by writing to this table — it does not maintain a parallel limits table:

```python
# billing/services/plan_service.py
quota.cap_files = plan.daily_upload_cap
```

Other overridable limits (max file size, group member cap, retention days) are **not** on `UploadQuota`. They live on the `PlanLimit` model in `billing`. See `app/billing/docs/limits_and_gating.md`.

## Open Questions (PRD §10)

- Are caps global or per-user? → Modelled **per-user** (`cap_files` on the row), with `settings.daily_upload_cap` as the default seed.
- Who changes caps — admin panel or plan? → Currently only `billing`. An internal admin panel would also write this column.
