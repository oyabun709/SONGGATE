from datetime import datetime
from pydantic import BaseModel


class ReportRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    pipeline_id: str
    release_id: str
    summary: dict
    findings: list
    created_at: datetime
