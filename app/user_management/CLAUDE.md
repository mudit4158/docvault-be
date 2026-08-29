# user_management — Module Context

## Scope

Owns **identity, authentication, and social structure**. Everything about *who a user is* and *who they are connected to*.

| Concern | Owned here? |
|---|---|
| Account creation, login, PIN | ✅ Yes |
| JWT issuance | ✅ Yes (via `shared.auth`) |
| Upload quota counters & caps | ✅ Yes |
| Groups, memberships, invitations | ✅ Yes |
| Document upload / storage | ❌ → `document_management` |
| Share grants on documents | ❌ → `document_management` |
| Paid plans, credits, feature gating | ❌ → `billing` |

## Deep-Dive Docs

CLAUDE.md stays a map. Low-level logic lives in `docs/`:

| Doc | Covers |
|---|---|
| [`docs/auth_flow.md`](docs/auth_flow.md) | Registration, login, PIN hashing, token lifecycle, biometric handoff |
| [`docs/group_rules.md`](docs/group_rules.md) | Member cap, invitation lifecycle, admin invariant, cascade rules |
| [`docs/quota_rules.md`](docs/quota_rules.md) | Daily counter, reset window, check-order, plan overrides |

**Read the relevant `docs/` file before implementing anything in this module.** Add a new `docs/*.md` whenever a feature's logic is more than a paragraph — do not grow this file.

## Entities

| Model | File | Notes |
|---|---|---|
| `Account` | `models/account.py` | Root identity — phone + PIN hash |
| `UploadQuota` | `models/quota.py` | 1-to-1 with Account; PK is `account_id` |
| `Group` | `models/group.py` | Name, description, creator |
| `Membership` | `models/group.py` | Composite PK `(group_id, user_id)`; role admin/member |
| `Invitation` | `models/group.py` | Unique on `(group_id, invited_user_id)` |

## Implementation Status

| Feature | Status |
|---|---|
| Login (`POST /auth/login`) | ✅ **Sample flow** — copy this pattern |
| Get profile (`GET /auth/me`) | ✅ Built |
| Registration | ⬜ Not built — spec in `docs/auth_flow.md` |
| PIN change | ⬜ Not built |
| Quota read/enforce | ⬜ Not built — spec in `docs/quota_rules.md` |
| Group CRUD | ⬜ Not built — spec in `docs/group_rules.md` |
| Invitations | ⬜ Not built — spec in `docs/group_rules.md` |
| Member management | ⬜ Not built — spec in `docs/group_rules.md` |

## Planned Route Surface

Routes marked ⬜ above are not yet implemented. When building them, register new router files in `app/main.py`.

| Method | Path | Feature |
|---|---|---|
| `POST` | `/auth/register` | Registration |
| `POST` | `/auth/login` | ✅ Built |
| `GET` | `/auth/me` | ✅ Built |
| `PATCH` | `/me/pin` | PIN change |
| `GET` | `/me/quota` | Quota status |
| `GET` `POST` | `/groups` | List / create |
| `GET` `DELETE` | `/groups/{id}` | Detail / delete |
| `POST` | `/groups/{id}/invite` | Invite |
| `GET` | `/groups/{id}/members` | Member list |
| `DELETE` | `/groups/{id}/members/{uid}` | Remove member |
| `PATCH` | `/groups/{id}/members/{uid}/role` | Transfer admin |
| `GET` | `/invitations` | Pending invites for caller |
| `POST` | `/invitations/{id}/accept` \| `/decline` | Respond |

## Sample Flow — Login

`router/auth.py` → `services/auth_service.py::AuthService.login`

The reference pattern for this module:

```python
class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def login(self, phone: str, pin: str) -> TokenResponse:
        result = await self.db.execute(select(Account).where(Account.phone == phone))
        account = result.scalar_one_or_none()
        if account is None:
            raise NotFoundError("No account found for this phone number")
        if not verify_pin(pin, account.pin_hash):
            raise ForbiddenError("Incorrect PIN")
        return TokenResponse(access_token=create_access_token(str(account.id)))
```

Routes stay thin — they resolve dependencies and delegate. All logic sits in the service.

## Inter-Module Boundaries

- This module imports **nothing** from `document_management` or `billing` at module scope.
- `document_management` imports `Account` and `UploadQuota` from here (read + increment quota, verify ownership).
- `billing` writes to `UploadQuota.cap_files` to apply paid plan overrides.
- **Group deletion** must revoke share grants, which live in `document_management`. Do this with a *function-local* import inside `GroupService.delete()` to avoid a circular import at module load:
  ```python
  async def delete(self, group_id, caller_id):
      from app.document_management.services.share_service import ShareService
      await ShareService(self.db).revoke_all_for_group(group_id)
      ...
  ```

## Non-Negotiable Invariants

1. Every group has **exactly one** admin at all times.
2. Member cap (`settings.group_member_cap`) is checked at **invite** time, not accept time.
3. `Account` and `UploadQuota` are created in the **same transaction** — never an account without a quota row.
4. Deleting a group revokes `ShareGrant` rows; it **never** deletes `Document` rows.
5. PIN is stored only as a bcrypt hash. Never log, return, or store the plain PIN.
