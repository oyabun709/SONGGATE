"""
Pipeline service — thin query layer over the Scan model.

The /pipelines router exposes running/queued scans as "pipelines"
in the API surface.  Completed scans are surfaced via /reports.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scan import Scan, ScanStatus


class PipelineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_org(self, org_id: uuid.UUID) -> list[Scan]:
        result = await self.db.execute(
            select(Scan)
            .where(Scan.org_id == org_id)
            .order_by(Scan.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_org(self, scan_id: str, org_id: uuid.UUID) -> Scan | None:
        result = await self.db.execute(
            select(Scan).where(
                Scan.id == scan_id,
                Scan.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def cancel(self, scan_id: str, org_id: uuid.UUID) -> Scan | None:
        scan = await self.get_for_org(scan_id, org_id)
        if scan and scan.status in (ScanStatus.queued, ScanStatus.running):
            scan.status = ScanStatus.failed
            scan.completed_at = datetime.now(timezone.utc)
            # TODO: revoke Celery task via celery_app.control.revoke(task_id)
            await self.db.commit()
            await self.db.refresh(scan)
        return scan
