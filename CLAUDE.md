# DocVault Backend — AI Context

Secure personal document vault. Users upload, organise, and share documents with trusted people through groups. FastAPI backend serving both the Android app and the responsive web app.

**Stack:** Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · Alembic · Pydantic v2

## Current State — Read This First

| Module | State |
|---|---|
| `shared` | ✅ DB, auth, storage interface, exceptions, pagination, **audit framework** |
| `user_management` | ✅ **Complete** — register, login, groups, invitations, members, admin transfer |
| `document_management` | ⬜ Scaffold — one sample flow (`GET /documents`) |
| `billing` | ⬜ Scaffold — one sample flow (`GET /billing/subscriptions`) |

14 tables · 20 endpoints · **101 tests passing**.

Everything not marked ✅ is **specified but not implemented**. Before building, find the spec — each module's `CLAUDE.md` has a status table pointing at the `docs/*.md` describing it. The specs encode decisions already made; do not re-derive them.

⚠️ **No baseline Alembic migration is committed.** Generate it against Postgres before running against a real database.

## Documentation Convention

Two tiers, deliberately:

| File | Holds | Size |
|---|---|---|
| `<module>/CLAUDE.md` | Scope, entities, route surface, status, boundaries, invariants | Short — a map |
| `<module>/docs/*.md` | Algorithms, state machines, orderings, edge cases, rationale | As long as needed |

**When a feature's logic outgrows a paragraph, write a new `docs/*.md` and link it from the module's `CLAUDE.md`. Do not grow the `CLAUDE.md`.** It is loaded on every interaction; the detail belongs one hop away.

## Module Map

| Module | Owns |
|---|---|
| [`app/shared/`](app/shared/CLAUDE.md) | DB session, JWT auth, storage interface, exceptions, pagination |
| [`app/user_management/`](app/user_management/CLAUDE.md) | Accounts, auth, quotas, groups, memberships, invitations |
| [`app/document_management/`](app/document_management/CLAUDE.md) | Documents, tags, share grants, access logs, download, scan save |
| [`app/billing/`](app/billing/CLAUDE.md) | Subscriptions, credits, feature gating, limit overrides |

### Dependency Direction

```
user_management  ──▶ shared
document_management ──▶ shared, user_management, billing
billing          ──▶ shared, user_management
```

`shared` imports from nobody. Two cross-module calls are deliberate and documented at both ends:

- `user_management.GroupService.delete()` → `document_management.ShareService.revoke_all_for_group()` (function-local import, avoids a circular import)
- `billing` writes `user_management.UploadQuota.cap_files` on plan change

## Cross-Cutting Invariants

Never violate these, in any module:

1. **Soft-delete only.** `Document.deleted_at` is the sole deletion signal. Never `DELETE FROM documents`.
2. **Every document read filters `deleted_at IS NULL`** unless the endpoint is explicitly the trash listing.
3. **Group delete revokes share grants; it never deletes documents.** They return to their owners' vaults.
4. **Access log is append-only.** No UPDATE, no DELETE, ever. It outlives the file it describes.
5. **Size check precedes quota check.** An oversized file is rejected before the daily counter is touched, so it never consumes quota.
6. **Revoking a share grant emits an `AccessLog` `revoke` event** in the same transaction.
7. **Rename preserves `Document.original_extension`** regardless of what the user types.
8. **Compression sizes are computed server-side per file.** Never hardcode ratios.
9. **Services never call `db.commit()`.** The `get_db` dependency owns the transaction.
10. **`FeatureGate.require()` runs before any DB write** on a paid-feature path — and never on a read path.

## Data Model

12 tables. The vault is **flat** — no folders, no document hierarchy.

```
Account ─┬─< UploadQuota      (1-to-1)
         ├─< Membership >─── Group ─┬─< Invitation
         ├─< Subscription           └─< ShareGrant >─┐
         ├─< PlanLimit                               │
         └─< Document >──────────────────────────────┤
                    ├─< DocTag >─── Tag              │
                    └─< AccessLog                    │
                         (append-only, outlives doc) ┘
```

## Configurable Parameters

Defined in `app/config.py` as `Settings`, loaded from env. All four are raisable per-account by a paid plan — see `app/billing/docs/limits_and_gating.md`.

| Parameter | Default | Env var | Effective value read from |
|---|---|---|---|
| Daily upload cap | 10 files | `DAILY_UPLOAD_CAP` | `UploadQuota.cap_files` |
| Max file size | 20 MB | `MAX_UPLOAD_SIZE_BYTES` | `PlanLimit` → falls back to settings |
| Max group members | 20 | `GROUP_MEMBER_CAP` | `PlanLimit` → falls back to settings |
| Soft-delete retention | 10 days | `SOFT_DELETE_RETENTION_DAYS` | `PlanLimit` → falls back to settings |

Never read these directly from `settings` on a request path — resolve the per-account effective value.

## Authentication & Audit

**Every route is authenticated except `POST /auth/register` and `POST /auth/login`.** Add `account_id: uuid.UUID = Depends(get_current_account_id)` to anything new.

Credentials live on `AuthIdentity`, never on `Account` — that split is what makes OTP and SSO additive. See `app/user_management/docs/auth_flow.md`.

**Audit is automatic.** A model declaring `__audited__ = True` has every INSERT/UPDATE/DELETE recorded, attributed to the caller that the auth dependency stamped into a ContextVar. Services never call the audit layer — do not add manual audit calls. Secrets (`secret_hash`, `password_hash`, `pin_hash`, `token_hash`) are never written. See `app/shared/docs/audit_framework.md`.

`AuditLog` ≠ `AccessLog`. The first is infrastructure across all tables; the second is the per-document product feature of PRD §4.8.

## Conventions

- **Thin routers, fat services.** Routers resolve dependencies and delegate. All logic in `ServiceClass(db).method()`.
- **Typed models.** `Mapped[T]` / `mapped_column()` throughout. No legacy `Column()`.
- **Timezone-aware timestamps.** `Base.type_annotation_map` maps `datetime` → `DateTime(timezone=True)`. The code compares against `datetime.now(timezone.utc)`; naive columns raise on Postgres.
- **Typed exceptions.** Raise from `app.shared.exceptions` — FastAPI maps them to the right status.
- **`model_config = {"from_attributes": True}`** on response schemas so `.model_validate(orm_obj)` works.

## Adding a Feature

1. Find the spec in the owning module's `docs/`. Follow it — the decisions are already made.
2. Model → schema → service → router, in that order.
3. Register a new router file in `app/main.py`.
4. **Add any new model module to the import list in `alembic/env.py`** — autogenerate silently skips models it cannot see.
5. `alembic revision --autogenerate -m "..."` **against Postgres**, never SQLite (dialect leaks into the migration).
6. Test in `tests/<module>/`.
7. Flip the row from ⬜ to ✅ in the module's `CLAUDE.md` status table.

## Commands

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload    # docs at /docs
pytest
```

## Product Reference

Behaviour comes from the PRD (v1.3) and the engineering handoff doc, both in `../docs/product/`. The `docs/*.md` files cite them by section — "PRD §4.3", "engineering handoff §3.2" — so any rule traces back to its source. When a spec and your intuition disagree, the spec wins; if the spec is silent, check its "Open Questions" section before inventing an answer.

Cross-repo documentation lives in `../docs/` — start at `../docs/README.md`:

- `../docs/TRACKER.md` — done vs. pending across backend and Android, plus the open questions and decisions log
- `../docs/hld/` — system architecture, backend module design, data model

**When you finish a feature, flip its row in the module's status table here *and* in `../docs/TRACKER.md`.** They must not drift.
