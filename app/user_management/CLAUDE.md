# user_management — Module Context

## Scope

Owns **identity, authentication, and social structure**. Everything about *who a user is* and *who they are connected to*.

| Concern | Owned here? |
|---|---|
| Accounts, login, credentials | ✅ Yes |
| Multi-mode auth providers (password / OTP / SSO) | ✅ Yes |
| Upload quota counters & caps | ✅ Yes |
| Groups, memberships, invitations | ✅ Yes |
| Document upload / storage | ❌ → `document_management` |
| Share grants on documents | ❌ → `document_management` |
| Paid feature access | ❌ → `billing` |
| The audit trail itself | ❌ → `shared/audit` (automatic) |

## Deep-Dive Docs

CLAUDE.md stays a map. Low-level logic lives in `docs/`:

| Doc | Covers |
|---|---|
| [`docs/auth_flow.md`](docs/auth_flow.md) | Identity/credential split, provider dispatch, registration, login, uniform-failure rationale, tokens |
| [`docs/group_rules.md`](docs/group_rules.md) | Admin invariant, member cap, invitation lifecycle, 404-over-403 rule, cascades |
| [`docs/quota_rules.md`](docs/quota_rules.md) | Daily counter, lazy reset, check ordering, plan overrides |

**Read the relevant doc before changing anything here.** Add a new `docs/*.md` when logic outgrows a paragraph — do not grow this file.

## Entities

| Model | File | Notes |
|---|---|---|
| `Account` | `models/account.py` | Identity only — **holds no credentials** |
| `AuthIdentity` | `models/auth_identity.py` | One row per login method per account |
| `UploadQuota` | `models/quota.py` | 1-to-1 with Account; PK is `account_id` |
| `Group` | `models/group.py` | |
| `Membership` | `models/group.py` | Composite PK `(group_id, user_id)`; role admin/member |
| `Invitation` | `models/group.py` | Unique on `(group_id, invited_user_id)` |

All six are `__audited__ = True`.

## Implementation Status

| Feature | Status |
|---|---|
| Registration | ✅ Built |
| Login (password mode) | ✅ Built |
| Profile (`GET /auth/me`) | ✅ Built |
| Password change | ✅ Built |
| Quota read | ✅ Built |
| Group CRUD | ✅ Built |
| Invitations (invite / list / accept / decline) | ✅ Built |
| Member list, remove, leave | ✅ Built |
| Admin transfer | ✅ Built |
| Group delete / last member leaves → revoke share grants | ✅ Built — calls `ShareService.revoke_all_for_group` |
| Quota enforcement (counter increment) | ✅ Built — `services/quota_service.py`, called by the upload path |
| OTP login | ⬜ Future scope — phase 2 |
| Google / Apple SSO | ⬜ Future scope — phase 3 |
| Biometric MFA | ⬜ Future scope — phase 4 |
| Revocable sessions | ⬜ Future scope — third-party auth service |

## Route Surface

| Method | Path | Auth | Role |
|---|---|---|---|
| `POST` | `/auth/register` | ❌ | — |
| `POST` | `/auth/login` | ❌ | — |
| `GET` | `/auth/me` | ✅ | — |
| `POST` | `/auth/me/password` | ✅ | + current password |
| `GET` | `/auth/me/quota` | ✅ | — |
| `GET` `POST` | `/groups` | ✅ | any |
| `GET` | `/groups/{id}` | ✅ | member |
| `PATCH` `DELETE` | `/groups/{id}` | ✅ | **admin** |
| `POST` | `/groups/{id}/invite` | ✅ | **admin** |
| `GET` | `/groups/{id}/members` | ✅ | member |
| `DELETE` | `/groups/{id}/members/me` | ✅ | member (leave) |
| `DELETE` | `/groups/{id}/members/{uid}` | ✅ | **admin** |
| `POST` | `/groups/{id}/transfer-admin` | ✅ | **admin** |
| `GET` | `/invitations` | ✅ | invitee |
| `POST` | `/invitations/{id}/accept` \| `/decline` | ✅ | invitee |

`register` and `login` are the **only** unauthenticated routes in the whole API.

⚠️ `/members/me` must stay declared **before** `/members/{uid}` in `router/groups.py` — FastAPI matches in declaration order.

## Non-Negotiable Invariants

1. **Exactly one admin per group**, always. Guarded on remove-self, sole-admin-leave, and transfer.
2. **Member cap counts the admin**, and is checked at **both** invite and accept time.
3. **`Account` + `AuthIdentity` + `UploadQuota` are created in one transaction.** Never an account without a quota row.
4. **404, not 403, for non-members.** A 403 confirms the group exists. 403 is only for a member lacking the role.
5. **Login failures are uniform.** Same status and body for unknown phone and wrong password, plus a dummy hash on the not-found path to equalise timing.
6. **Credentials never live on `Account`.** They go in `AuthIdentity`.
7. **Passwords are capped at 72 bytes** — bcrypt's limit; beyond it two passwords could collide.
8. **Group delete revokes share grants; it never deletes documents.**

## Inter-Module Boundaries

- Imports **nothing** from `document_management` or `billing` at module scope.
- `document_management` imports `Account`, `UploadQuota` and `Membership` from here.
- `billing` writes `UploadQuota.cap_files` on plan change.
- Group deletion must call into `document_management.ShareService` with a **function-local** import (see `group_service.delete`).

## Adding a Login Mode

Four steps, no migration — `AUTH_PROVIDERS` already reserves `otp`, `google`, `apple`:

1. Subclass `AuthProvider` in `services/providers.py`.
2. Register it in `_PROVIDERS`.
3. Make `LoginRequest` a discriminated union over per-mode models.
4. Test it.

`AuthService.login`, the routes, and the auth dependency do not change.
