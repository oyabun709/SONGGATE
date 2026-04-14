import uuid
from datetime import date, datetime

from pydantic import BaseModel

from models.release import ReleaseStatus, SubmissionFormat


class ReleaseCreate(BaseModel):
    title: str
    artist: str
    submission_format: SubmissionFormat
    upc: str | None = None
    release_date: date | None = None
    external_id: str | None = None


class ReleaseRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    external_id: str | None
    title: str
    artist: str
    upc: str | None
    release_date: date | None
    submission_format: SubmissionFormat
    raw_package_url: str | None
    status: ReleaseStatus
    created_at: datetime
