# billing — Module Context

## Scope

Owns **monetisation**: subscriptions, prepaid credits, plan-based limit overrides, and the gate that decides whether a paid feature is available.

| Concern | Owned here? |
|---|---|
| Subscriptions & lifecycle | ✅ Yes |
| Prepaid credit balance & consumption | ✅ Yes |
| Plan-based limit overrides | ✅ Yes |
| `FeatureGate` — the paid-feature check | ✅ Yes |
| Payment provider integration | ✅ Yes (not yet chosen) |
| Who a user is | ❌ → `user_management` |
| Daily upload counter | ❌ → `user_management` (billing *writes* the cap) |
| Documents | ❌ → `document_management` |

## Why This Is a Module Now, Not Later

Every paid feature is post-MVP (PRD §7), so it is tempting to defer this entirely. It exists now for one structural reason: **paid plans raise the upload cap, the file-size cap, the group member cap, and the retention window** (PRD §8.3).

Those limits are read on the hot path of `document_management` upload and `user_management` invite. If billing is bolted on later, every one of those call sites has to be reopened. Defining the boundary now — even with the logic unimplemented — means the call sites are written against it from the start.

**All MVP features stay free within the default limits** (PRD §8.1). Nothing in this module gates an MVP feature.

## Deep-Dive Docs

| Doc | Covers |
|---|---|
| [`docs/subscription_model.md`](docs/subscription_model.md) | Plan structure, lifecycle, cancellation, expiry semantics |
| [`docs/credits.md`](docs/credits.md) | Credit packs, consumption, confirmation, zero-balance blocking |
| [`docs/limits_and_gating.md`](docs/limits_and_gating.md) | `FeatureGate` contract, limit override resolution, call sites |

## Entities

| Model | File | Notes |
|---|---|---|
| `Subscription` | `models/subscription.py` | One row per account per `feature_key` |
| `PlanLimit` | `models/subscription.py` | Per-account limit overrides |

## Paid Features (PRD §7)

Each is a `feature_key`. All are post-MVP.

| `feature_key` | Feature | Charging |
|---|---|---|
| `video_to_pdf` | PDF overview from an uploaded video | Per video |
| `versioning` | Document version history | Monthly |
| `auto_doc_type` | OCR/ML document-type detection | Per document |
| `group_encryption` | Per-group encryption key | Monthly per group |
| `p2p_storage` | Store on the user's own system over P2P | Monthly |
| `pdf_signing` | Digitally sign PDFs | Per signature |
| `ai_editing` | AI-based PDF/image editing | Per edit |
| `bundle` | Covers every paid feature | Monthly |

## Implementation Status

| Feature | Status |
|---|---|
| Subscription status (`GET /billing/subscriptions`) | ✅ **Sample flow** — copy this pattern |
| `FeatureGate` | ⬜ Not built — `docs/limits_and_gating.md` |
| Subscribe / cancel | ⬜ Not built — `docs/subscription_model.md` |
| Credit packs & consumption | ⬜ Not built — `docs/credits.md` |
| Limit override resolution | ⬜ Not built — `docs/limits_and_gating.md` |
| Billing history | ⬜ Not built |
| Payment provider integration | ⬜ Not built — provider not yet chosen (PRD §10) |
| Renewal / payment-failure notifications | ⬜ Not built |

## Planned Route Surface

| Method | Path | Feature |
|---|---|---|
| `GET` | `/billing/subscriptions` | ✅ Built — caller's active subscriptions |
| `GET` | `/billing/plans` | Plan catalogue with prices |
| `POST` | `/billing/subscribe` | Start a subscription |
| `DELETE` | `/billing/subscriptions/{id}` | Cancel (stays active till period end) |
| `GET` | `/billing/history` | Billing history |
| `POST` | `/billing/credits/purchase` | Buy a credit pack |
| `GET` | `/billing/credits/balance` | Remaining credits |

## Sample Flow — List Subscriptions

`router/subscriptions.py` → `services/subscription_service.py::SubscriptionService.list_active`

Demonstrates the module's central rule: **an active subscription is one that has not expired**, and expiry is evaluated at read time against `expires_at`. There is no scheduled job flipping an `is_active` flag — a cron that lags leaves users paying for a locked feature or using an expired one.

```python
select(Subscription).where(
    Subscription.account_id == account_id,
    Subscription.expires_at > datetime.now(timezone.utc),
)
```

## Inter-Module Boundaries

- Imports `Account` and `UploadQuota` from `user_management` (to apply cap overrides).
- Imports **nothing** from `document_management`.
- Other modules call **into** `FeatureGate` — this module does not call out to them:

  ```python
  from app.billing.services.feature_gate import FeatureGate

  await FeatureGate(db).require(account_id, "pdf_signing")
  ```

  Raises `FeatureNotAvailableError` (HTTP 402) when the feature is not unlocked.

## Non-Negotiable Invariants

1. **`FeatureGate.require()` runs before any DB write** in a paid-feature flow. Never charge a credit for work that then fails.
2. **Active is computed, never stored.** No `is_active` boolean.
3. **A cancelled subscription stays active until `expires_at`** (PRD §8.4). Cancelling sets `cancelled_at`; it does not shorten `expires_at`.
4. **Unused credits never expire** with a subscription (PRD §8.4). Credit balance and subscription lifetime are independent.
5. **Documents created with a paid feature stay accessible after expiry** (PRD §8.4). Gate the *action*, never the resulting document.
6. **Limit overrides are written to the owning module's table** — billing sets `UploadQuota.cap_files`; it does not maintain a shadow copy.
