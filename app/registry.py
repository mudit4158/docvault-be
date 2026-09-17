"""Single import point for the full database schema.

Importing this module imports every model AND installs the generated audit
tables, in that order. Audit tables are derived from the models, so they can
only be built once every model is registered on `Base`.

**Import this — never the model modules individually — anywhere the complete
schema must exist:**

    app/main.py          so the app sees the same metadata as the migrations
    alembic/env.py       so autogenerate sees every table
    tests/conftest.py    so create_all builds everything

Adding a model: add its import below. Forgetting means its table is silently
missing from migrations, with no error anywhere.
"""

# --- models -----------------------------------------------------------------
# ruff: noqa: F401  (imported for registration, not use)
import app.billing.models.plan_limit
import app.billing.models.subscription
import app.document_management.models.access_log
import app.document_management.models.doc_tag
import app.document_management.models.document
import app.document_management.models.share_grant
import app.document_management.models.tag
import app.user_management.models.account
import app.user_management.models.auth_identity
import app.user_management.models.group
import app.user_management.models.invitation
import app.user_management.models.membership
import app.user_management.models.otp_attempt
import app.user_management.models.quota

# --- audit tables -----------------------------------------------------------
# Must come after the model imports above.
from app.shared.audit.registry import install_audit_tables

install_audit_tables()
