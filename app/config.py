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
    storage_backend: str = "local"
    local_storage_path: str = "./uploads"
    aws_bucket_name: str = ""
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Encryption
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
