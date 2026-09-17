"""Firebase Admin SDK initialization — lazy, once per process.

Used only by the OTP login provider
(`app.user_management.services.providers.FirebaseOtpProvider`) to verify ID
tokens the Android app already obtained from Firebase Phone Auth. Firebase
Phone Auth itself is entirely client-driven — the app talks to Firebase
directly, and Firebase sends the SMS and owns the resend cooldown. This
backend never sends an SMS; it only ever verifies the token afterward.
"""

import firebase_admin
from firebase_admin import credentials

from app.config import settings


def ensure_firebase_app() -> None:
    """No-op if an app is already initialized (real runtime, or a test that
    initialized its own fake app) — firebase_admin supports exactly one
    default app per process."""
    try:
        firebase_admin.get_app()
    except ValueError:
        if settings.firebase_credentials_path:
            cred = credentials.Certificate(settings.firebase_credentials_path)
            firebase_admin.initialize_app(cred)
        else:
            # Application Default Credentials — the real-deployment path
            # (Workload Identity on Cloud Run/GCE), same pattern as GCSStorage.
            firebase_admin.initialize_app()
