# Audit Framework — Implementation Detail

**Status:** built. Generic capture, pluggable storage, per-table by default.

## What This Is — and Is Not

| | Audit framework (here) | `AccessLog` (document_management) |
|---|---|---|
| Purpose | Infrastructure — what changed, when, by whom | Product feature (PRD §4.8) |
| Scope | Every audited table | One document |
| Audience | Operators, investigations | The document's owner |
| UI surface | None | Detail screen + CSV export |
| Written by | Session listeners, automatically | Services, explicitly |

Deliberately separate. Overloading `AccessLog` would break its per-document contract and force dropping its `document_id NOT NULL`.

## Two Independent Halves

```
CAPTURE                          STORAGE
listeners.py                     sinks/
  session events  ──▶ AuditRecord ──▶  AuditSink.emit()
                                         ├── PerTableSink    (default)
                                         ├── SingleTableSink
                                         └── NullSink
```

Capture never knows where records go; a sink never knows how they were produced. Changing one does not touch the other — that separation is the point of the design.

## Opting a Model In

```python
class Group(Base):
    __audited__ = True
    __audit_exclude__ = {"some_sensitive_column"}   # optional
```

That is the whole integration. **Services never call the audit layer** — automatic capture removes manual logging's standard failure mode, where one forgotten call leaves a silent hole nothing catches in review.

Currently audited: `accounts`, `auth_identities`, `groups`, `memberships`, `invitations`, `upload_quotas`, `subscriptions`, `plan_limits`.

## Per-Table Storage (default)

Each audited table gets a generated shadow table: `accounts` → `accounts_audit`.

```
accounts_audit
  audit_id               uuid    PK
  audit_operation        varchar INSERT | UPDATE | DELETE
  audit_actor_id         uuid    null for unauthenticated actions
  audit_at               timestamptz
  audit_changed_fields   json    null for INSERT/DELETE
  ── mirrored from accounts, all nullable ──
  id, phone, display_name, created_at, updated_at
```

Why per-table rather than one shared table:

- **Typed columns.** `role`, `expires_at`, `credit_balance` keep their types and are directly queryable and indexable, instead of collapsing into a JSON blob that needs casting.
- **Excluded columns do not exist.** `auth_identities_audit` has no `secret_hash` column at all — stronger than filtering at write time, because there is nowhere for a secret to go even if a future sink forgets to check.
- **Cheaper queries and indexes.** "History of this row" is an index seek on real columns.

Costs, accepted: the schema grows with the model count, and every audited model's migration has a matching audit-table migration.

### Snapshot semantics

Each audit row holds the **full row state**, not just the delta:

| Operation | `snapshot` holds | `audit_changed_fields` |
|---|---|---|
| INSERT | the new row | null |
| UPDATE | the row **after** the change | the changed column names |
| DELETE | the row **before** it was destroyed | null |

So a single audit row reconstructs the record at that point in time; `audit_changed_fields` says what moved.

### Generated, not declared

Audit tables are built from the models at import time by `registry.install_audit_tables()`, so they cannot drift from the source schema.

That imposes an ordering requirement: **models must all be imported before the tables are built.** `app/registry.py` is the one place that guarantees it — import that, never the model modules individually, and never call `install_audit_tables()` yourself.

Enum columns are mirrored as `VARCHAR`, deliberately. Audit history has to keep values that a later migration retires from the enum, and reusing a named PostgreSQL enum across tables would try to `CREATE TYPE` twice.

## Swapping the Sink

`AUDIT_SINK` in the environment:

| Value | Behaviour |
|---|---|
| `per_table` | Shadow table per audited table, typed columns (**default**) |
| `single_table` | One shared `audit_logs` table, JSON values |
| `none` | Auditing disabled |

`audit_logs` is only registered on the metadata when `single_table` is actually selected, so the unused table is never created.

### Adding a sink

```python
class KafkaSink(AuditSink):
    name = "kafka"

    def emit(self, session: Session, records: Sequence[AuditRecord]) -> None:
        ...

register_sink(KafkaSink)
```

A sink runs **inside the flush** of the transaction that produced the change, so audit rows commit or roll back with the work they describe. It must therefore be cheap and must not block on external I/O — an external sink should enqueue, not call out.

## Capture Mechanics

Two hooks, because neither alone has everything:

| Hook | Has | Lacks |
|---|---|---|
| `before_flush` | Attribute history, so old values are readable | Client-side-default primary keys not yet populated |
| `after_flush` | Primary keys populated | History has been reset |

So `before_flush` captures and stashes on `session.info`; `after_flush` resolves keys and emits. Sinks use **Core** inserts, not ORM, so they cannot cascade into another flush.

An UPDATE where no column actually differs writes **no row** — assigning a field its existing value is common in service code and would otherwise fill the trail with entries describing nothing.

## Actor Propagation

The listeners run deep inside a flush, far from the request, so the actor cannot be a function argument. A **`ContextVar`** carries it — set by `get_current_account_id`, read by the listener. A ContextVar rather than a global because each concurrent request needs its own value.

For jobs and tests:

```python
from app.shared.audit import acting_as

with acting_as(account_id):
    ...
```

**A null actor is expected, not a bug** — registration and login happen before anyone is authenticated.

## Known Limits

| Limit | Detail |
|---|---|
| ORM-only | Bulk operations (`session.execute(update(...))`) and raw SQL bypass the listeners — they never load objects into the session. Use ORM operations on audited tables, or add a database trigger. |
| Same transaction | Audit rows roll back with the work they describe. Correct for "what changed", but a **failed** action leaves no trace — a rejected login is not recorded. Security-event logging is a separate concern. |
| No retention policy | Rows accumulate indefinitely. Per-table partitioning or archival is needed before this gets large. |
| Not queryable via API | By design — audit is not a UI surface. |

## Architectural Note

This package puts models in `shared/`, amending HLD 02's "shared holds no business logic". An audit framework is infrastructure, not domain logic, and every module writes to it — placing it in any one module would invert the dependency direction for the others.
