"""
Scan management endpoints.

POST  /releases/{release_id}/scan                        — create + run a new scan
GET   /releases/{release_id}/scans                       — scan history for a release
GET   /scans/{scan_id}                                   — single scan detail
GET   /scans/{scan_id}/results                           — full ScanResult corpus
PATCH /scans/{scan_id}/results/{result_id}/resolve       — mark result resolved
GET   /scans/{scan_id}/report                            — presigned S3 URL for PDF report
POST  /scans/{scan_id}/report/regenerate                 — re-trigger report generation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from dependencies.tier_gate import check_scan_limit
from models.organization import Organization
from models.release import Release
from models.scan import Scan, ScanGrade, ScanStatus
from models.scan_result import ScanResult, ResultStatus
from schemas.scan import ScanRead
from schemas.scan_result import ScanDetailRead, ScanResultRead, ResolveRequest
from services.scan_orchestrator import ScanOrchestrator

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Request / response schemas
# ──────────────────────────────────────────────────────────────────────────────

class ScanCreateRequest(BaseModel):
    dsps: list[str] | None = None      # default: all 5 DSPs
    layers: list[str] | None = None    # default: all 6 layers


class ScanHistoryRead(ScanRead):
    """Scan list item — no results corpus."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# POST /releases/{release_id}/scan
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/releases/{release_id}/scan",
    response_model=ScanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_scan(
    release_id: str,
    payload: ScanCreateRequest = ScanCreateRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Create a new scan for a release and start the QA pipeline.

    Returns 202 Accepted immediately.  The scan status transitions:
      queued → running → complete | failed

    Poll GET /scans/{scan_id} for progress.
    """
    # Verify release belongs to org
    result = await db.execute(
        select(Release).where(
            Release.id == uuid.UUID(release_id),
            Release.org_id == org.id,
        )
    )
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Release not found")

    # Enforce monthly scan quota
    await check_scan_limit(org)

    # Create scan row in queued state
    scan = Scan(
        id=uuid.uuid4(),
        release_id=uuid.UUID(release_id),
        org_id=org.id,
        status=ScanStatus.queued,
        layers_run=payload.layers or [],
        created_at=datetime.now(timezone.utc),
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    # Run the orchestrator in the background so we can return 202 immediately
    scan_id = str(scan.id)
    org_id = str(org.id)
    dsps = payload.dsps
    layers = payload.layers

    background_tasks.add_task(
        _run_scan_background,
        release_id=release_id,
        scan_id=scan_id,
        org_id=org_id,
        dsps=dsps,
        layers=layers,
    )

    return scan


async def _run_scan_background(
    release_id: str,
    scan_id: str,
    org_id: str,
    dsps: list[str] | None,
    layers: list[str] | None,
) -> None:
    """Background task that runs the full scan orchestrator."""
    orchestrator = ScanOrchestrator()
    try:
        await orchestrator.run_scan(
            release_id=release_id,
            scan_id=scan_id,
            org_id=org_id,
            dsps=dsps,
            layers=layers,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Background scan failed for scan %s", scan_id
        )


# ──────────────────────────────────────────────────────────────────────────────
# GET /releases/{release_id}/scans
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/releases/{release_id}/scans",
    response_model=list[ScanHistoryRead],
)
async def list_scans_for_release(
    release_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Return scan history for a release, newest first."""
    # Verify release ownership
    result = await db.execute(
        select(Release).where(
            Release.id == uuid.UUID(release_id),
            Release.org_id == org.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Release not found")

    scans_result = await db.execute(
        select(Scan)
        .where(
            Scan.release_id == uuid.UUID(release_id),
            Scan.org_id == org.id,
        )
        .order_by(Scan.created_at.desc())
    )
    return list(scans_result.scalars().all())


# ──────────────────────────────────────────────────────────────────────────────
# GET /scans/{scan_id}
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/scans/{scan_id}", response_model=ScanRead)
async def get_scan(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Return a single scan by ID."""
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    return scan


# ──────────────────────────────────────────────────────────────────────────────
# GET /scans/{scan_id}/results
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/scans/{scan_id}/results", response_model=ScanDetailRead)
async def get_scan_results(
    scan_id: str,
    layer: str | None = Query(None, description="Filter by layer"),
    severity: str | None = Query(None, description="Filter by severity"),
    resolved: bool | None = Query(None, description="Filter by resolved status"),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Return a scan with its full ScanResult corpus."""
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")

    query = select(ScanResult).where(ScanResult.scan_id == uuid.UUID(scan_id))

    if layer:
        query = query.where(ScanResult.layer == layer)
    if severity:
        query = query.where(ScanResult.severity == severity)
    if resolved is not None:
        query = query.where(ScanResult.resolved == resolved)

    # Order: critical first, then by layer
    query = query.order_by(
        ScanResult.severity.desc(),
        ScanResult.layer,
        ScanResult.created_at,
    )

    results_query = await db.execute(query)
    results = list(results_query.scalars().all())

    # Build response manually to avoid ORM lazy-load issues
    scan_dict = {
        "id": scan.id,
        "release_id": scan.release_id,
        "org_id": scan.org_id,
        "status": scan.status,
        "readiness_score": scan.readiness_score,
        "grade": scan.grade,
        "total_issues": scan.total_issues,
        "critical_count": scan.critical_count,
        "warning_count": scan.warning_count,
        "info_count": scan.info_count,
        "layers_run": scan.layers_run,
        "started_at": scan.started_at,
        "completed_at": scan.completed_at,
        "created_at": scan.created_at,
        "results": results,
    }
    return ScanDetailRead.model_validate(scan_dict)


# ──────────────────────────────────────────────────────────────────────────────
# PATCH /scans/{scan_id}/results/{result_id}/resolve
# ──────────────────────────────────────────────────────────────────────────────

@router.patch(
    "/scans/{scan_id}/results/{result_id}/resolve",
    response_model=ScanResultRead,
)
async def resolve_scan_result(
    scan_id: str,
    result_id: str,
    payload: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Mark a scan result as resolved (acknowledged / fixed)."""
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")

    result_query = await db.execute(
        select(ScanResult).where(
            ScanResult.id == uuid.UUID(result_id),
            ScanResult.scan_id == uuid.UUID(scan_id),
        )
    )
    sr = result_query.scalar_one_or_none()
    if not sr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Result not found")

    sr.resolved = True
    sr.resolution = payload.resolution
    sr.resolved_by = payload.resolved_by
    sr.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sr)
    return sr


# ──────────────────────────────────────────────────────────────────────────────
# GET /scans/{scan_id}/report
# ──────────────────────────────────────────────────────────────────────────────

class ReportURLResponse(BaseModel):
    scan_id: str
    report_url: str                   # presigned S3 GET URL (valid 1 hour)
    report_generated_at: datetime | None
    filename: str


@router.get("/scans/{scan_id}/report", response_model=ReportURLResponse)
async def get_scan_report(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Return a presigned S3 download URL for the scan's PDF report.

    If the report has not been generated yet, fires the generation task
    and returns 202 Accepted so the client can poll.
    """
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")

    if scan.status != "complete":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Scan is not yet complete — report will be available after the scan finishes.",
        )

    # Report not generated yet — fire the task and tell the client to retry
    if not scan.report_url:
        try:
            from tasks.generate_report import generate_report_task
            generate_report_task.delay(scan_id)
        except Exception:
            pass
        raise HTTPException(
            status.HTTP_202_ACCEPTED,
            detail="Report generation started — retry in a few seconds.",
        )

    # Generate a presigned GET URL from the stored S3 key
    presigned_url = _make_presigned_url(scan.report_url)
    filename = scan.report_url.rsplit("/", 1)[-1]

    return ReportURLResponse(
        scan_id=scan_id,
        report_url=presigned_url,
        report_generated_at=scan.report_generated_at,
        filename=filename,
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /scans/{scan_id}/report/regenerate
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/scans/{scan_id}/report/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_report(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Re-trigger PDF generation (e.g. after resolving issues)."""
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.status != "complete":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Scan is not complete.")

    from tasks.generate_report import generate_report_task
    generate_report_task.delay(scan_id)
    return {"detail": "Report generation queued.", "scan_id": scan_id}


def _make_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned S3 GET URL for a stored report key."""
    from config import settings

    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url

    import boto3
    s3 = boto3.client("s3", **kwargs)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key},
        ExpiresIn=expires_in,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Shared helper
# ──────────────────────────────────────────────────────────────────────────────

async def _get_scan_for_org(
    db: AsyncSession, scan_id: str, org_id: uuid.UUID
) -> Scan | None:
    result = await db.execute(
        select(Scan).where(
            Scan.id == uuid.UUID(scan_id),
            Scan.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()
