from datetime import datetime
from pydantic import BaseModel
from models.pipeline import PipelineStatus


class PipelineRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    release_id: str
    celery_task_id: str | None
    status: PipelineStatus
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
