# Auth Flow — Implementation Detail

**Status:** password mode built. OTP, SSO and biometric MFA are future scope.

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
{ mode: "password", phone, password }   -> PasswordProvider   (built)
{ mode: "otp",      phone, code }       -> OtpProvider        (phase 2)
{ mode: "google",   id_token }          -> GoogleProvider     (phase 3)
```

Each provider has exactly one job — turn credentials into an `account_id`. Token issuance, the audit actor, and the auth dependency are all mode-agnostic and never change when a mode is added.

To add a mode:
1. Subclass `AuthProvider` in `services/providers.py`.
2. Register it in `_PROVIDERS`.
3. Add the value to `AUTH_PROVIDERS` in `models/auth_identity.py` — the enum already reserves `otp`, `google` and `apple`, so no migration is needed.
4. Convert `LoginRequest` into a discriminated union over per-mode models.

Nothing in the routes or `AuthService.login` changes.

## Registration

`POST /auth/register` — unauthenticated.

```
1. Validate phone (E.164) and password (8..72 chars)  -> 422
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

`POST /auth/register` and `POST /auth/login` are the **only** unauthenticated routes in the API. Everything else carries `Depends(get_current_account_id)`.

| Route | Auth |
|---|---|
| `POST /auth/register` | ❌ no caller exists yet |
| `POST /auth/login` | ❌ no caller exists yet |
| `GET /auth/me` | ✅ |
| `POST /auth/me/password` | ✅ + current password |
| `GET /auth/me/quota` | ✅ |
| everything under `/groups`, `/invitations` | ✅ |

## Password Change

`POST /auth/me/password` — authenticated, and re-verifies the current password. Possession of a valid token is not sufficient to change the credential: a token might be borrowed from an unlocked device.

## Future Scope

| Item | Note |
|---|---|
| OTP login | `OtpProvider` + an `otp_challenges` table. Sets `verified_at`. |
| Google / Apple SSO | Verify the upstream ID token, match on `provider_subject` = `sub`. No local secret. |
| Biometric MFA | Cannot be a client-asserted flag — a patched client sets it to true. Requires an Android Keystore keypair with `setUserAuthenticationRequired(true)`, a server nonce, and signature verification, so the signature proves a biometric occurred on an enrolled device. |
| Revocable sessions | Via a third-party auth service, not built in-house. |
| Account deletion | Not specified in the PRD. |
