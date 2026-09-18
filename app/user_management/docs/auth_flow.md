# Auth Flow — Implementation Detail

**Status:** password mode and OTP (Firebase Phone Auth) mode built, coexisting on the same account. SSO and biometric MFA are future scope.

## Identity vs Credentials

The central decision: `Account` holds **no secrets**. How an account proves itself lives in `AuthIdentity`, one row per method.

```
accounts          who you are        (phone, display_name — no credentials)
auth_identities   how you prove it   (provider, provider_subject, secret_hash)
```

An account may hold several identities — a password *and* Google *and* OTP, all resolving to the same person. Linking a new method is an INSERT. Nothing about `accounts` changes, and no existing credential is migrated.

This is why login modes are additive rather than a rewrite each time.

## Provider Dispatch

`POST /auth/login` carries a `mode` field routed to one `AuthProvider`:

```
{ mode: "password", phone, password }        -> PasswordProvider     (built)
{ mode: "otp",      firebase_id_token }      -> FirebaseOtpProvider  (built)
{ mode: "google",   id_token }                -> GoogleProvider      (phase 3)
```

Each provider has exactly one job — turn credentials into an `account_id`. Token issuance, the audit actor, and the auth dependency are all mode-agnostic and never change when a mode is added.

**`LoginRequest` stayed a single flat model, not a discriminated union**, despite that being the documented target shape below every time a mode was added. Reason: the Android client's JSON serializer (kotlinx.serialization, `encodeDefaults=false`, the project default) omits `mode` from the wire entirely for a password login, since `"password"` is the client-side default. A Pydantic discriminated union requires the discriminator key to be present in the input to resolve which member to validate against — it would reject every existing password login the moment it shipped. Field requirements are enforced manually instead, via a `model_validator` keyed on `mode` (see `schemas/account.py`).

To add a mode:
1. Subclass `AuthProvider` in `services/providers.py`.
2. Register it in `_PROVIDERS`.
3. Add the value to `AUTH_PROVIDERS` in `models/auth_identity.py` — the enum already reserves `google` and `apple`, so no migration is needed.
4. Add the mode's fields to `LoginRequest` as optional, and a branch in its `model_validator`.

Nothing in the routes or `AuthService.login`'s shape changes — only the small `if data.mode == "otp"` branch that picks which credential dict to build.

## OTP Login (Firebase Phone Auth)

**Entirely client-driven.** The Android app talks to Firebase directly — Firebase sends the SMS and owns the resend cooldown; this backend never sends an SMS and has no visibility into how many times a code was resent. The backend's only job is verifying the ID token Firebase handed the app once the user entered the correct code, via `firebase_admin.auth.verify_id_token()` (`app/shared/firebase.py` lazily initializes the Admin SDK — a service-account key locally, Application Default Credentials in a real deployment, same pattern as `GCSStorage`).

**Uniform failure does NOT apply here**, deliberately, unlike `PasswordProvider`. A valid Firebase token already proves the caller controls that phone number — "no DocVault account for this number" tells them nothing they couldn't already prove by owning the phone. What's still worth throttling: someone with a phone they control repeatedly presenting valid tokens to probe whether *other* numbers are registered isn't possible here (the token proves ownership of *their own* number only) — but hammering login attempts for their own unregistered number is cheap for them and costs us a DB write each time, so `OtpAttempt` (keyed by phone, not account — no account may exist) tracks failed match attempts and locks a phone out for `settings.otp_lockout_minutes` after `settings.otp_max_verify_attempts` failures. Resets to zero the moment that phone successfully matches an account. A malformed/expired/forged token never reaches this table — there's no phone number to attribute it to, and forging a valid-looking Firebase token isn't a realistic attack surface this needs to defend against.

OTP and password are **additive**, not exclusive — `AuthIdentity`'s one-row-per-provider-per-account design means an account can hold both simultaneously (see "Identity vs Credentials" above). Logging in via OTP for the first time creates the `otp` identity row automatically; it doesn't touch the account's `password` identity at all. `verified_at` is refreshed on every successful OTP login (not just the first), since a fresh Firebase token proves phone ownership again each time — unlike a password, there's no reason to leave it stuck at its original value.

The verification+throttling logic (`verify_phone_and_resolve_account` in `services/firebase_verification.py`) is shared with **Forgot Password** below — both need exactly the same thing: proof of phone ownership, resolved to an existing account, with the same per-phone `OtpAttempt` lockout. They share the same `OtpAttempt` row for a given phone too — failing five times via forgot-password and then trying OTP login hits the same lockout, not two independent counters.

## Forgot Password

`POST /auth/password/forgot` — unauthenticated (necessarily: the caller can't log in, that's the premise). Body: `{ firebase_id_token, new_password }`.

```
1. verify_phone_and_resolve_account(db, firebase_id_token) -> Account, or 401
2. Find that account's "password" AuthIdentity
3. identity.secret_hash = bcrypt(new_password)
```

No `current_password` field, unlike `POST /auth/me/password` — a verified Firebase token is the alternate factor standing in for it. `new_password` goes through the exact same complexity validator as registration (`_check_password_strength` in `schemas/account.py`). Every account has a password identity from registration, so step 2 finding none is treated as an unreachable-but-handled case (`NotFoundError`), not silently created.

Deliberately does **not** revoke the account's existing access token(s) — matches the already-documented "no revocable sessions" gap under Tokens below. A stolen-but-not-yet-expired token stays valid even after a password reset; this is an accepted limitation, not something this endpoint tries to paper over.

### Check-phone pre-check

`POST /auth/password/forgot/check-phone` — unauthenticated. Body: `{ phone }`. 204 if an account exists for that phone, 404 otherwise. Never touches Firebase — it's a plain DB lookup, called by the client *before* triggering Firebase's SMS send, so an unregistered number never wastes an OTP.

⚠️ **Deliberate phone-number-enumeration tradeoff.** Anyone, unauthenticated, can now probe any number and learn whether it has a DocVault account — the same category of leak `POST /auth/login`'s uniform failure exists specifically to prevent. Accepted here on purpose: unlike login, letting an OTP be sent for a number nobody registered has a real cost (an SMS charge) and no product benefit, so the enumeration tradeoff was judged worth it for this one endpoint. `POST /auth/login` and `POST /auth/password/forgot` itself keep their uniform-failure behavior — this pre-check is the one deliberate exception, not a precedent for loosening the others.

## Registration

`POST /auth/register` — unauthenticated.

```
1. Validate phone (E.164) and password (8..72 chars, upper+lower+digit+special)  -> 422
2. Phone already registered?                          -> 409
3. INSERT Account(phone, display_name)
4. INSERT AuthIdentity(provider="password", subject=phone, secret_hash=bcrypt(password))
5. INSERT UploadQuota(cap_files=settings.daily_upload_cap)
```

Steps 3–5 share **one transaction**. An `Account` without an `UploadQuota` would fail the first time that user tried to upload, so partial success is not an acceptable outcome.

`verified_at` on the identity stays null. A password proves nothing about ownership of the phone number; it is set when OTP verification lands in phase 2.

## Login

`POST /auth/login` — unauthenticated.

```
1. get_provider(mode)                     -> 401 on an unknown mode
2. provider.authenticate(db, credentials) -> account_id, or 401
3. create_access_token(str(account_id))
4. identity.last_used_at = now()
```

### Uniform failure — deliberate

`PasswordProvider` returns the **identical** 401 body for "no such account" and "wrong password", and hashes a dummy value on the not-found path so the response time matches.

Distinguishing them lets anyone enumerate which phone numbers hold a DocVault account. For a vault of identity documents, *"this number belongs to a DocVault user"* is itself a disclosure. The cost is a slightly less helpful error message.

> ⚠️ `POST /groups/{id}/invite` returns 404 for an unregistered phone and therefore **does** leak registration status. It is at least authenticated, so only registered users can probe. Revisit if the threat model tightens.

## Password Storage

`bcrypt` directly, cost factor 12. Not passlib: its last release (1.7.4, 2020) reads `bcrypt.__about__.__version__`, removed in bcrypt 4.1, which raises on every hash.

bcrypt **rejects** input over 72 bytes rather than truncating, so the schema caps passwords at 72. Without that cap two different long passwords could hash identically and both would unlock the account.

`verify_password` returns `False` on a malformed hash rather than raising — a corrupt stored value must be a failed login, not a 500.

## Tokens

Stateless JWT, HS256, `sub` = account UUID, expiry from `settings.access_token_expire_minutes` (60 min).

> ⚠️ **Known gap.** Stateless tokens cannot be revoked: logout is a client-side discard and a stolen token stays valid until expiry. Accepted for now; the decision is to adopt a third-party auth service rather than build session management in-house. Tracked as future scope.

## The Audit Actor

`get_current_account_id` stamps the audit actor as a side effect:

```python
set_actor(account_id)
return account_id
```

Every row the request writes is then attributed automatically. No service passes an actor id, and none can forget to.

Registration and login write rows with a **null actor** — correct, since no one is authenticated yet.

## Authenticated Surface

`POST /auth/register`, `POST /auth/login`, `POST /auth/password/forgot` and `POST /auth/password/forgot/check-phone` are the **only** unauthenticated routes in the API. Everything else carries `Depends(get_current_account_id)`.

| Route | Auth |
|---|---|
| `POST /auth/register` | ❌ no caller exists yet |
| `POST /auth/login` | ❌ no caller exists yet |
| `POST /auth/password/forgot` | ❌ the whole point — caller can't log in |
| `POST /auth/password/forgot/check-phone` | ❌ deliberate enumeration tradeoff — see Forgot Password above |
| `GET /auth/me` | ✅ |
| `POST /auth/me/password` | ✅ + current password |
| `GET /auth/me/quota` | ✅ |
| everything under `/groups`, `/invitations` | ✅ |

## Password Change

`POST /auth/me/password` — authenticated, and re-verifies the current password. Possession of a valid token is not sufficient to change the credential: a token might be borrowed from an unlocked device.

## Future Scope

| Item | Note |
|---|---|
| Google / Apple SSO | Verify the upstream ID token, match on `provider_subject` = `sub`. No local secret. |
| Biometric MFA | Cannot be a client-asserted flag — a patched client sets it to true. Requires an Android Keystore keypair with `setUserAuthenticationRequired(true)`, a server nonce, and signature verification, so the signature proves a biometric occurred on an enrolled device. |
| Revocable sessions | Via a third-party auth service, not built in-house. |
| Account deletion | Not specified in the PRD. |
