"""
Report service — completed scans with their full ScanResult corpus.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scan import Scan, ScanStatus
from models.scan_result import ScanResult


class ReportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_org(self, org_id: uuid.UUID) -> list[Scan]:
        """Return completed scans for this org, newest first."""
        result = await self.db.execute(
            select(Scan)
            .where(
                Scan.org_id == org_id,
                Scan.status == ScanStatus.complete,
            )
            .order_by(Scan.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_results(
        self, scan_id: str, org_id: uuid.UUID
    ) -> tuple[Scan, list[ScanResult]] | None:
        """Return (scan, results) or None if not found / wrong org."""
        scan_result = await self.db.execute(
            select(Scan).where(
                Scan.id == scan_id,
                Scan.org_id == org_id,
            )
        )
        scan = scan_result.scalar_one_or_none()
        if not scan:
            return None

        results_query = await self.db.execute(
            select(ScanResult)
            .where(ScanResult.scan_id == scan_id)
            .order_by(ScanResult.severity, ScanResult.layer)
        )
        results = list(results_query.scalars().all())
        return scan, results

    async def resolve_result(
        self,
        result_id: str,
        org_id: uuid.UUID,
        resolution: str,
        resolved_by: str,
    ) -> ScanResult | None:
        """Mark a single ScanResult as resolved."""
        from datetime import datetime, timezone
        # Verify the result belongs to this org via the scan join
        row = await self.db.execute(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(
                ScanResult.id == result_id,
                Scan.org_id == org_id,
            )
        )
        sr = row.scalar_one_or_none()
        if not sr:
            return None
        sr.resolved = True
        sr.resolution = resolution
        sr.resolved_by = resolved_by
        sr.resolved_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(sr)
        return sr
