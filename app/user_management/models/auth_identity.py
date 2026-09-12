import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base

# Login modes. Only "password" is implemented; the rest are declared so the
# enum does not need migrating when each phase lands.
#   password -> phone + password           (phase 1, built)
#   otp      -> phone + SMS one-time code  (phase 2)
#   google   -> Google ID token            (phase 3)
#   apple    -> Apple ID token             (phase 3)
AUTH_PROVIDERS = ("password", "otp", "google", "apple")


class AuthIdentity(Base):
    """One way a given account can authenticate.

    An account may hold several rows — a password AND Google AND OTP all
    resolving to the same identity. Linking a new method is an INSERT; no
    change to `accounts` and no migration of existing credentials.

    See docs/auth_flow.md for the provider dispatch design.
    """

    __tablename__ = "auth_identities"
    __audited__ = True
    # Belt and braces: the listener excludes secret_hash globally too. An audit
    # trail that copies password hashes turns one compromise into two.
    __audit_exclude__ = {"secret_hash"}

    __table_args__ = (
        # One account per (provider, subject): a phone number cannot map to two
        # accounts for the same login mode.
        UniqueConstraint("provider", "provider_subject", name="uq_auth_provider_subject"),
        # An account holds at most one identity per provider.
        UniqueConstraint("account_id", "provider", name="uq_auth_account_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(
        Enum(*AUTH_PROVIDERS, name="auth_provider"), nullable=False
    )
    # The identifier within that provider: the phone number for password/otp,
    # the `sub` claim for google/apple.
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    # Populated for "password" only. Federated providers verify upstream, so
    # there is no local secret to store.
    secret_hash: Mapped[str | None] = mapped_column(String(256))

    verified_at: Mapped[datetime | None] = mapped_column()
    last_used_at: Mapped[datetime | None] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
