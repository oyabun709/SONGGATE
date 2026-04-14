from datetime import datetime
from pydantic import BaseModel
from models.release import ReleaseStatus


class ReleaseCreate(BaseModel):
    name: str
    version: str


class ReleaseRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    version: str
    artifact_url: str | None
    status: ReleaseStatus
    created_at: datetime
    updated_at: datetime
