# DocVault — Backend

FastAPI backend for DocVault, a secure personal document vault. Serves both the Android app and the responsive web app.

> **Working with Claude Code in this repo?** Start at [`CLAUDE.md`](CLAUDE.md), then read the `CLAUDE.md` of the module you are changing.

## Stack

Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · Alembic · Pydantic v2

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                 # then fill in the values
alembic upgrade head
uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs

## Layout

```
app/
├── shared/               # DB session, JWT auth, storage interface, exceptions, pagination
├── user_management/      # Accounts, auth, groups, memberships, invitations, quotas
├── document_management/  # Documents, tags, share grants, access logs, download
└── billing/              # Subscriptions, credits, feature gating, limit overrides
```

Each module owns its own `models/`, `schemas/`, `services/`, and `router/`, plus a `CLAUDE.md` and a `docs/` folder.

## Documentation Convention

Two tiers, deliberately:

| File | Holds | Keep it |
|---|---|---|
| `<module>/CLAUDE.md` | Scope, entity list, route surface, implementation status, boundaries, invariants | Short — a map |
| `<module>/docs/*.md` | Algorithms, state machines, edge cases, orderings, rationale | As long as it needs to be |

When a feature's logic outgrows a paragraph, write a new `docs/*.md` and link it from the module's `CLAUDE.md` — do not grow the `CLAUDE.md`. This keeps the file Claude always reads small while the detail stays one hop away.

## Current State

Scaffold only. Each module has **one sample flow** end-to-end (model → schema → service → router) as a reference pattern. Everything else is specified in the `docs/` files and marked ⬜ in each module's `CLAUDE.md`.

| Module | Sample flow |
|---|---|
| `user_management` | `POST /api/v1/auth/login` |
| `document_management` | `GET /api/v1/documents` |
| `billing` | `GET /api/v1/billing/subscriptions` |

## Migrations

```bash
alembic revision --autogenerate -m "add x"
alembic upgrade head
alembic downgrade -1
```

Two things to know:

**Always autogenerate against PostgreSQL**, never SQLite. Alembic renders the migration using the dialect of whatever database `DATABASE_URL` points at, so a SQLite-generated migration bakes in `CURRENT_TIMESTAMP` defaults and the wrong column types, then fails or silently misbehaves on Postgres.

**Autogenerate only sees models imported in `alembic/env.py`.** Add every new model module to that import list, or its table is silently missing from the migration with no error.

No baseline migration is committed yet — generate it against your Postgres instance:

```bash
alembic revision --autogenerate -m "initial schema"
```

Then review it before applying. One thing autogenerate cannot express is the partial unique index on `share_grants` (one *active* grant per document+group). Add it by hand to the initial migration:

```python
op.execute(
    "CREATE UNIQUE INDEX uq_active_grant ON share_grants "
    "(document_id, group_id) WHERE revoked_at IS NULL"
)
```

## Tests

```bash
pytest
```

Tests run against in-memory SQLite with the schema built from `Base.metadata`.

## Product Reference

Behaviour is specified by the PRD (v1.3) and the engineering handoff doc. The `docs/*.md` files cite them by section — e.g. "PRD §4.3", "engineering handoff §3.2" — so a rule can always be traced back to its source.
