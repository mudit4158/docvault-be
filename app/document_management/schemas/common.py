import uuid
from typing import Literal

from pydantic import BaseModel

DocumentType = Literal["aadhaar", "voter_id", "pan", "passport", "other"]
SharePermission = Literal["view", "download"]
# What the caller can do with a document. `download` implies `view`.
MyPermission = Literal["owner", "download", "view"]


class PersonSummary(BaseModel):
    """A person shown next to a document: its owner, or who did something."""

    id: uuid.UUID
    display_name: str
