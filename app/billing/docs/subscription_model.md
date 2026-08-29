# Subscription Model — Implementation Detail

Source: PRD §7 (Future Plans), §8.1 (Plan Structure), §8.4 (Billing & Lifecycle).

## Plan Structure

- All MVP features are **free** within default limits. Nothing in the MVP is gated.
- Each post-MVP feature is sold as an independent add-on.
- A user may subscribe to a single feature, or to `bundle` which covers all of them.
- Recurring features bill **monthly**. Usage-based features bill through **prepaid credits** (see `credits.md`).

One `Subscription` row per `(account_id, feature_key)`. Subscribing to `bundle` creates one row with `feature_key = "bundle"` — not seven rows.

## Lifecycle

```
      subscribe
          │
          ▼
    ┌──────────┐   cancel     ┌───────────┐   expires_at passes   ┌─────────┐
    │  active  │ ───────────▶ │ cancelled │ ────────────────────▶ │ expired │
    │          │              │ (still    │                       │         │
    │          │              │  usable)  │                       │         │
    └──────────┘              └───────────┘                       └─────────┘
         │                                                             ▲
         └──────────────── expires_at passes (renewal failed) ─────────┘
```

| State | `cancelled_at` | `expires_at` | Feature usable |
|---|---|---|---|
| active | `NULL` | future | ✅ |
| cancelled | set | future | ✅ — until the period ends |
| expired | either | past | ❌ |

## Active Is Computed, Never Stored

There is no `is_active` column and no job that flips one. Activity is a function of `expires_at` evaluated at read time:

```python
def is_active(sub: Subscription) -> bool:
    return sub.expires_at > datetime.now(timezone.utc)
```

A nightly job that marks rows inactive is wrong in both directions: it lags behind real expiry (users keep a feature they stopped paying for) and it can run early (users lose a feature they paid for). Computing it removes the failure mode entirely.

`cancelled_at` deliberately does **not** affect usability. Per PRD §8.4: *"A cancelled subscription stays active till the end of the paid period."* Cancelling sets `cancelled_at` and stops auto-renewal. It never shortens `expires_at`.

## Cancellation

`DELETE /billing/subscriptions/{id}`

```
1. Verify the subscription belongs to the caller   → 403 otherwise
2. SET cancelled_at = now()
3. Leave expires_at untouched
4. Mark the plan as non-renewing with the payment provider
```

The user keeps the feature until `expires_at`. There is no refund path in MVP.

## Renewal

For monthly features, renewal extends `expires_at` by one month on successful payment.

| Outcome | Action |
|---|---|
| Payment succeeds | `expires_at += 1 month` |
| Payment fails | Leave `expires_at` alone; notify the user (PRD §8.4). The subscription lapses naturally when the date passes |
| `cancelled_at` is set | Do not attempt renewal |

Notify the user **before** a renewal charge and **on** a payment failure (PRD §8.4). Both are outbound notifications, not blocking steps.

## Expiry Semantics — What Gets Locked

This distinction matters and is easy to get wrong:

> "A paid feature is locked once the subscription expires. **Documents already created using a paid feature stay accessible after expiry.**" — PRD §8.4

So gate the **action**, never the **artefact**.

| On expiry | Behaviour |
|---|---|
| Signing a new PDF | ❌ Blocked |
| Opening a PDF signed last month | ✅ Still works |
| Running AI edit | ❌ Blocked |
| Viewing a previously AI-edited document | ✅ Still works |
| Creating a new document version | ❌ Blocked |
| Reading existing version history | ✅ Still works |

`FeatureGate` is therefore only ever called on write/action paths. It must never appear in a read path for an existing document. A read path that calls it is a bug.

## Unused Credits Survive Expiry

Per PRD §8.4: *"Unused credits do not expire with the subscription."*

Credit balance is on the `Subscription` row for the usage-billed feature, but it is **not** governed by `expires_at`. When a subscription lapses, the balance stays. Resubscribing restores access to a balance that was never cleared. Do not zero a balance on expiry or cancellation. See `credits.md`.

## Payment Provider

Not yet chosen. PRD §10 leaves open: UPI, cards, net banking; and whether billing is in-app on Android or web-only.

Keep the provider behind an interface in `services/payment_provider.py` (mirroring `shared/storage/interface.py`) so the choice does not leak into subscription logic. Google Play billing policy may force in-app purchase on Android, which would mean two provider implementations behind one interface.

## Billing History

`GET /billing/history` — an append-only ledger of charges, separate from `Subscription`. A subscription row is current state; history is the audit trail. Do not reconstruct history from subscription rows.

Model this when the payment provider is chosen — its webhook payloads determine the shape.
