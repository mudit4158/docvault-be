# Credits — Implementation Detail

Source: PRD §8.2.

## Model

Usage-billed features consume prepaid credits. One credit per chargeable action.

`credit_balance` lives on the `Subscription` row for the relevant `feature_key`. Pack size and price are open questions (PRD §10).

## Which Features Use Credits

| `feature_key` | Billing | Uses credits |
|---|---|---|
| `video_to_pdf` | Per video processed | ✅ |
| `auto_doc_type` | Per document scanned | ✅ |
| `pdf_signing` | Per signature applied | ✅ |
| `ai_editing` | Per edit applied | ✅ |
| `versioning` | Monthly | ❌ |
| `group_encryption` | Monthly per group | ❌ |
| `p2p_storage` | Monthly | ❌ |

Monthly features check subscription validity only. Credit-billed features check **both** — a valid subscription *and* a non-zero balance.

## Consumption Flow

The UI shows the cost, asks for confirmation, then acts (PRD §8.2). The confirmation is client-side; the server sees two separate calls.

```
1. Client: GET the cost of the action        → server returns credit cost
2. Client: shows cost + confirmation dialog
3. User confirms
4. Client: POST the action
5. Server:
     a. FeatureGate.require(account_id, feature_key)   → 402 if not subscribed
     b. Lock the subscription row (SELECT ... FOR UPDATE)
     c. Check credit_balance > 0                       → 402 if zero
     d. Perform the work
     e. DECREMENT credit_balance
     f. Commit
```

Steps b–f are one transaction. Two rules follow:

**Decrement after the work succeeds, not before.** If the work fails, the transaction rolls back and the credit is not consumed. A user must never be charged for a failed action.

**Lock the row.** Without `SELECT ... FOR UPDATE`, two concurrent actions both read a balance of 1 and both proceed, driving the balance negative.

```python
result = await db.execute(
    select(Subscription)
    .where(
        Subscription.account_id == account_id,
        Subscription.feature_key == feature_key,
    )
    .with_for_update()
)
```

## Zero Balance

Per PRD §8.2: *"System blocks the action if the credit balance is zero."*

Raise `FeatureNotAvailableError` (402) with a message that distinguishes the two failure modes — the client shows different UI for "buy a pack" vs "subscribe":

- Not subscribed → *"Feature 'pdf_signing' requires an active subscription"*
- Subscribed, zero balance → *"No credits remaining for 'pdf_signing'"*

Balance must never go negative. The row lock plus the pre-check guarantee this; a `CHECK (credit_balance >= 0)` constraint is a cheap backstop.

## Purchasing

`POST /billing/credits/purchase`

```
1. Charge via the payment provider
2. On success: INCREMENT credit_balance
3. Record the purchase in billing history
```

Increment only after the provider confirms. Make the handler idempotent on the provider's transaction id — payment webhooks retry, and a double-credit is a real cost.

## Credits Outlive Subscriptions

Per PRD §8.4: *"Unused credits do not expire with the subscription."*

- Cancelling a subscription does **not** zero the balance.
- Expiry does **not** zero the balance.
- Resubscribing restores access to the balance that was there all along.

So `credit_balance` is deliberately independent of `expires_at`, even though both live on the same row. There is no code path anywhere that sets `credit_balance = 0`.

This is why `FeatureGate` checks subscription validity and balance as **two separate conditions** — a user can hold a positive balance on an expired subscription, and that balance must survive until they resubscribe.
