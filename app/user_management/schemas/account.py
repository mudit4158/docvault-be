import uuid
from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    phone: str
    pin: str


class RegisterRequest(BaseModel):
    phone: str
    pin: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountResponse(BaseModel):
    id: uuid.UUID
    phone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class QuotaResponse(BaseModel):
    files_used_today: int
    cap_files: int
    period_reset_at: datetime

    model_config = {"from_attributes": True}
