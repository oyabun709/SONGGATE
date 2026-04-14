from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.report import Report


class ReportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[Report]:
        result = await self.db.execute(select(Report).order_by(Report.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, report_id: str) -> Report | None:
        return await self.db.get(Report, report_id)
