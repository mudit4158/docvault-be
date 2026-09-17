# shared — AI Context

## Purpose

`shared` holds every utility that has **no business logic** and is needed by more than one module. Nothing in `shared` should import from `user_management`, `document_management`, or `billing`. Dependency flows inward only: modules import from `shared`, never the reverse.

## What Lives Here

| Sub-package / file | What it provides |
|---|---|
| `db/base.py` | `Base` — the single `DeclarativeBase` all models inherit from |
| `db/session.py` | `engine`, `AsyncSessionLocal`, `get_db` — the FastAPI session dependency |
| `auth/jwt.py` | `create_access_token(subject)`, `decode_token(token)` |
| `auth/dependencies.py` | `get_current_account_id` — FastAPI `Depends` that validates the bearer token and returns a `uuid.UUID` |
| `storage/interface.py` | `StorageBackend` abstract class + `get_storage()` factory (returns a process-wide singleton); concrete impls: `LocalStorage` (dev), `GCSStorage` (production) |
| `exceptions.py` | Typed `HTTPException` subclasses: `NotFoundError`, `UnauthorizedError`, `ForbiddenError`, `ConflictError`, `QuotaExceededError`, `FileTooLargeError` |
| `pagination.py` | `PageParams`, `PagedResponse[T]` |
| `audit/` | Automatic, table-agnostic audit trail — see below |

## Audit Framework

The one place `shared` owns a **model**. Deep dive: [`docs/audit_framework.md`](docs/audit_framework.md).

Opt a model in with one line; services never call the audit layer:

```python
class Group(Base):
    __audited__ = True
```

Every INSERT/UPDATE/DELETE is then captured by SQLAlchemy session listeners, attributed to the actor that `get_current_account_id` stamped into a ContextVar.

`secret_hash`, `password_hash`, `pin_hash` and `token_hash` are **never** written to the trail.

Do not confuse `AuditLog` with `AccessLog` in `document_management`: this is infrastructure covering every table; that is a product feature (PRD §4.8) scoped to one document and read by its owner.

> This places a model in `shared`, amending HLD 02's "shared holds no business logic". An audit framework is infrastructure and every module writes to it — putting it in any one module would invert the dependency direction for the others.

## Using `get_current_account_id`

```python
from app.shared.auth.dependencies import get_current_account_id

@router.get("/me")
async def me(account_id: uuid.UUID = Depends(get_current_account_id)):
    ...
```

Routes that must be **unauthenticated** (e.g. `POST /auth/login`) must not include this dependency.

## Using `get_db`

```python
from app.shared.db.session import get_db

@router.get("/items")
async def items(db: AsyncSession = Depends(get_db)):
    ...
```

The dependency commits on success and rolls back on any exception — services do not call `db.commit()` themselves.

## Planned, Not Yet Built

Two utilities are referenced by specs in other modules and belong here when built:

| File | Purpose | Referenced by |
|---|---|---|
| `encryption.py` | AES encrypt/decrypt at rest. Sits **above** the storage layer so any backend inherits it | `document_management/docs/document_lifecycle.md` |
| `compression.py` | Standard/High compression per file type; returns real byte sizes | `document_management/docs/download_and_compression.md` |

## Adding a New Shared Utility

Only add something to `shared` if it is genuinely needed by two or more modules. If it is only needed by one module, keep it inside that module.

`shared` must never import from `user_management`, `document_management`, or `billing`. If a utility needs one of their models, it is not a shared utility.

## Storage Backend

See `storage/interface.py`. To add a new backend (e.g. IPFS for P2P, which is on the post-MVP roadmap), subclass `StorageBackend` and register it in `get_storage()`.

## Exception Usage

Raise typed exceptions from services — FastAPI automatically converts them to the right HTTP status:

```python
from app.shared.exceptions import NotFoundError, ForbiddenError

raise NotFoundError("Document not found")
raise ForbiddenError("You do not own this document")
```
