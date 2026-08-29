import uuid
from datetime import datetime

from pydantic import BaseModel


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    feature_key: str
    credit_balance: int
    expires_at: datetime
    cancelled_at: datetime | None

    model_config = {"from_attributes": True}
