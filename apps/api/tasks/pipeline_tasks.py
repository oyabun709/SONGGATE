import asyncio
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="run_pipeline", max_retries=3, default_retry_delay=10)
def run_pipeline(self, scan_id: str, release_id: str) -> dict:
    """
    Execute the full QA pipeline for a release scan.

    Steps:
    1. Set Scan.status = running, record started_at
    2. Fetch release artifact URL from DB
    3. Download the artifact from S3
    4. Load enabled rules for the submission_format / DSP targets
    5. Run rules/engine.run_all() against the artifact bytes
    6. Persist ScanResult rows
    7. Aggregate counts → readiness_score → grade (PASS/WARN/FAIL)
    8. Update Scan.status = complete/failed, record completed_at
    9. Update Release.status = complete/failed
    """
    try:
        return asyncio.run(_run(scan_id, release_id))
    except Exception as exc:
        logger.exception("run_pipeline task failed for scan %s: %s", scan_id, exc)
        raise self.retry(exc=exc)


async def _run(scan_id: str, release_id: str) -> dict:
    from database import AsyncSessionLocal
    from models.scan import Scan
    from sqlalchemy import select

    # Look up org_id from the scan row (not passed by the caller)
    async with AsyncSessionLocal() as db:
        import uuid
        scan = await db.scalar(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        if scan is None:
            raise ValueError(f"Scan {scan_id} not found")
        org_id = str(scan.org_id)

    from services.scan_orchestrator import ScanOrchestrator
    orchestrator = ScanOrchestrator()
    completed_scan = await orchestrator.run_scan(
        release_id=release_id,
        scan_id=scan_id,
        org_id=org_id,
    )

    return {
        "scan_id": scan_id,
        "release_id": release_id,
        "status": completed_scan.status.value,
        "grade": completed_scan.grade.value if completed_scan.grade else None,
        "readiness_score": completed_scan.readiness_score,
        "total_issues": completed_scan.total_issues,
    }
