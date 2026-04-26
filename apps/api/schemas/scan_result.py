import uuid
from datetime import datetime
from pydantic import BaseModel

from models.scan_result import ResultStatus
from schemas.scan import ScanRead


class ScanResultRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    scan_id: uuid.UUID
    track_id: uuid.UUID | None
    layer: str
    rule_id: str
    severity: str
    status: ResultStatus
    message: str
    field_path: str | None
    actual_value: str | None
    expected_value: str | None
    fix_hint: str | None
    dsp_targets: list[str]
    resolved: bool
    resolution: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    created_at: datetime


class ScanDetailRead(ScanRead):
    """Scan with its full result corpus."""
    results: list[ScanResultRead] = []
    validated_fields: list | dict = []
    submission_format: str | None = None


class ResolveRequest(BaseModel):
    resolution: str
    resolved_by: str
