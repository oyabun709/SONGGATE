import uuid
from datetime import datetime
from pydantic import BaseModel

from models.scan import ScanStatus, ScanGrade


class ScanRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    release_id: uuid.UUID
    org_id: uuid.UUID
    status: ScanStatus
    readiness_score: float | None
    grade: ScanGrade | None
    total_issues: int
    critical_count: int
    warning_count: int
    info_count: int
    layers_run: list
    report_url: str | None = None
    report_generated_at: datetime | None = None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
