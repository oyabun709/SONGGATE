from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.pipeline import Pipeline, PipelineStatus


class PipelineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[Pipeline]:
        result = await self.db.execute(select(Pipeline).order_by(Pipeline.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, pipeline_id: str) -> Pipeline | None:
        return await self.db.get(Pipeline, pipeline_id)

    async def cancel(self, pipeline_id: str) -> None:
        pipeline = await self.get(pipeline_id)
        if pipeline and pipeline.status in (PipelineStatus.queued, PipelineStatus.running):
            pipeline.status = PipelineStatus.cancelled
            # TODO: revoke Celery task if celery_task_id is set
            await self.db.commit()
