import uuid

from pydantic import BaseModel, Field


class TagResponse(BaseModel):
    id: uuid.UUID
    label: str

    model_config = {"from_attributes": True}


class AddTagRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
