from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Storage
    #   local  files under local_storage_path (development, no GCP credentials needed)
    #   gcs    Google Cloud Storage (production)
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_path: str = "./uploads"
    gcs_bucket_name: str | None = None
    # Usually inferrable from credentials/ADC — set explicitly only if needed.
    gcs_project_id: str | None = None
    # Local dev only: path to a service-account JSON key. Leave unset in real
    # deployments — Workload Identity/ADC resolves credentials automatically
    # from the service account attached to the compute resource.
    gcs_credentials_path: str | None = None

    @model_validator(mode="after")
    def _validate_storage_config(self) -> "Settings":
        if self.storage_backend == "gcs" and not self.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME is required when STORAGE_BACKEND=gcs")
        return self

    # OTP login (Firebase Phone Auth). Firebase itself sends the SMS and owns
    # the resend cooldown — client-side, not something this backend controls.
    # What the backend DOES enforce: after `otp_max_verify_attempts` failed
    # attempts to log in as a phone number with no matching account (the one
    # enumeration surface left once Firebase has already proven phone
    # ownership), that phone is locked out for `otp_lockout_minutes`.
    firebase_project_id: str | None = None
    # Local dev only: path to a service-account JSON key. Leave unset in real
    # deployments — resolved via Application Default Credentials instead.
    firebase_credentials_path: str | None = None
    otp_max_verify_attempts: int = 5
    otp_lockout_minutes: int = 15

    # Encryption at rest. See app/shared/encryption.py for the expected format.
    encryption_key: str

    # Audit storage strategy. See app/shared/audit/sinks/.
    #   per_table     one shadow table per audited table, typed columns (default)
    #   single_table  one shared audit_logs table, JSON values
    #   none          auditing disabled
    audit_sink: str = "per_table"

    # Business rules (PRD §9 — all configurable)
    max_upload_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    daily_upload_cap: int = 10
    soft_delete_retention_days: int = 10
    group_member_cap: int = 20


settings = Settings()
