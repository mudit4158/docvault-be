# Limits & Feature Gating — Implementation Detail

Source: PRD §8.3 (Paid Limit Upgrades), §9 (Configurable Parameters).

This is the file that explains **why `billing` exists before any paid feature ships**.

## Two Separate Mechanisms

Do not conflate these:

| | Feature gating | Limit overrides |
|---|---|---|
| Question | "Can this account use feature X at all?" | "What is this account's cap for Y?" |
| Applies to | Post-MVP paid features | MVP features that already work |
| Mechanism | `FeatureGate.require()` raises 402 | A higher number in the owning module's table |
| Effect when absent | Action blocked | Default cap applies |

Feature gating blocks. Limit overrides only ever *raise* a number. An MVP feature is never blocked by billing.

## Feature Gating

```python
class FeatureGate:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def require(self, account_id: uuid.UUID, feature_key: str) -> None:
        """Raise FeatureNotAvailableError (402) unless the feature is unlocked.

        Unlocked means: an active subscription to this feature, or to `bundle`.
        For credit-billed features, also requires a non-zero balance.
        """
```

Two rules for call sites:

1. **Call it before any DB write.** Never do the work and then discover the account cannot pay for it.
2. **Only on action paths.** Per PRD §8.4, documents created with a paid feature stay accessible after expiry — so a read path for an existing document must never call `require()`. A `FeatureGate` call in a GET handler is almost certainly a bug.

`bundle` satisfies any `feature_key`. Check for the specific key **or** `bundle` in one query rather than two round trips.

## Limit Overrides

Four MVP limits are raisable by a paid plan (PRD §8.3):

| Limit | Default | Where the effective value lives |
|---|---|---|
| Daily upload cap | 10 files | `UploadQuota.cap_files` (in `user_management`) |
| Max file size | 20 MB | `PlanLimit.max_upload_size_bytes` |
| Max group members | 20 | `PlanLimit.group_member_cap` |
| Soft-delete retention | 10 days | `PlanLimit.retention_days` |

### Why the upload cap is different from the other three

The daily cap is **written into `UploadQuota.cap_files`**, the row the upload path already locks and reads. Billing writes to it on plan change:

```python
# On subscribing to a plan that raises the cap
quota.cap_files = plan.daily_upload_cap
```

The upload hot path stays a single locked row read — no join to billing, no second query, no cross-module call. See `user_management/docs/quota_rules.md`.

The other three are read far less often (once per upload for size, once per invite for members, once per job run for retention), so they live on `PlanLimit` and are resolved on demand.

### Resolution

`PlanLimit` holds only the columns an account has actually had raised. A missing row, or a `NULL` column, means "use the default".

```python
async def effective_limit(self, account_id: uuid.UUID, name: str) -> int:
    override = await self._get_plan_limit(account_id)
    value = getattr(override, name, None) if override else None
    return value if value is not None else getattr(settings, name)
```

Nullable columns rather than a fully-populated row means a change to a global default automatically applies to every account that has not been individually raised.

## Call Sites

Where these get wired in as features land. Written against this boundary from the start so nothing has to be reopened later:

| Module | Call site | What it needs |
|---|---|---|
| `document_management` | Upload — size check | `effective_limit(account_id, "max_upload_size_bytes")` |
| `document_management` | Upload — quota check | Already reads `UploadQuota.cap_files`; no billing call |
| `document_management` | Hard-delete job | `effective_limit(account_id, "retention_days")` per document owner |
| `document_management` | Signing, AI edit, versioning, video-to-PDF | `FeatureGate.require(...)` |
| `user_management` | Invite — member cap | `effective_limit(account_id, "group_member_cap")` for the group's admin |

The hard-delete job resolves retention **per document owner**, not globally — an account with extended retention must not have its files purged on the default schedule.

## Direction of Dependency

`billing` is called **into**; it does not call out.

```
document_management ──▶ billing.FeatureGate
user_management     ──▶ billing.PlanLimitService
billing             ──▶ user_management.UploadQuota   (write only, on plan change)
billing             ──▶ document_management            (never)
```

The one write billing makes into another module's table is `UploadQuota.cap_files`. That is deliberate and documented at both ends.

## Open Questions (PRD §10)

- Who changes configurable parameters — an internal admin panel, or only a plan? Currently only a plan. An admin panel would write the same `PlanLimit` row.
- Are limits global or per-user? Modelled **per-user**, with `settings` supplying the defaults.
- Prices, pack sizes, free trials — all unanswered. None of them change this structure.
