from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.registry  # noqa: F401  (models + generated audit tables)
import app.shared.audit  # noqa: F401  (registers the audit session listeners)
from app.billing.router.subscriptions import router as billing_router
from app.config import settings
from app.document_management.router.documents import router as documents_router
from app.shared.audit import configure_audit, get_sink
from app.user_management.router.accounts import router as accounts_router
from app.user_management.router.auth import router as auth_router
from app.user_management.router.groups import router as groups_router
from app.user_management.router.invitations import router as invitations_router

app = FastAPI(
    title="DocVault API",
    version="0.1.0",
    description="Secure personal document vault — Android + Web backend",
)

# Audit storage strategy comes from configuration, so it is a deployment
# choice rather than a code change.
configure_audit(get_sink(settings.audit_sink))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Router registration
#
# Every module owns its own router files under `<module>/router/`. Register
# each new router here. All routes sit behind /api/v1 so the mobile client can
# version independently of the web client.
#
# Currently registered:
#   user_management     -> auth, groups, invitations   (built)
#   document_management -> documents                   (sample flow only)
#   billing             -> subscriptions                (sample flow only)
# ---------------------------------------------------------------------------
app.include_router(auth_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(groups_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
