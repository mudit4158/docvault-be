from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.billing.router.subscriptions import router as billing_router
from app.document_management.router.documents import router as documents_router
from app.user_management.router.auth import router as auth_router

app = FastAPI(
    title="DocVault API",
    version="0.1.0",
    description="Secure personal document vault — Android + Web backend",
)

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
# Currently registered (one sample flow per module — features land incrementally):
#   user_management     -> auth
#   document_management -> documents
#   billing             -> subscriptions
# ---------------------------------------------------------------------------
app.include_router(auth_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
