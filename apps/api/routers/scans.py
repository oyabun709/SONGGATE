"""
Scan management endpoints.

POST  /releases/{release_id}/scan                        — create + run a new scan
GET   /scans                                             — all scans for this org (pipeline view)
GET   /releases/{release_id}/scans                       — scan history for a release
GET   /scans/{scan_id}                                   — single scan detail
GET   /scans/{scan_id}/results                           — full ScanResult corpus
PATCH /scans/{scan_id}/results/{result_id}/resolve       — mark result resolved
GET   /scans/{scan_id}/report                            — presigned S3 URL for PDF report
POST  /scans/{scan_id}/report/regenerate                 — re-trigger report generation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import io
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
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

    background_tasks.add_task(
        _run_scan_background,
        release_id=release_id,
        scan_id=str(scan.id),
        org_id=str(org.id),
        dsps=payload.dsps,
        layers=payload.layers,
    )

    return scan


# ──────────────────────────────────────────────────────────────────────────────
# POST /scans/bulk — bulk registration file scan (authenticated, stored in DB)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/scans/bulk", status_code=status.HTTP_200_OK)
async def create_bulk_scan(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
) -> JSONResponse:
    """
    Scan a bulk registration file (pipe-delimited, CSV, or PDF).

    Accepts .txt, .csv, .pdf files up to 5 MB.
    Runs parser → validator → scorer entirely in-process.

    The scan result is persisted as a Release + Scan + ScanResults in the database,
    scoped to the authenticated org, so it appears in scan history.

    Returns the full bulk scan result immediately (synchronous — no polling needed).
    """
    from datetime import date, timezone as tz
    from services.bulk.bulk_parser import parse_bulk_file, extract_text_from_pdf
    from services.bulk.bulk_validator import validate_bulk_file
    from services.bulk.bulk_scorer import score_bulk_scan
    from models.release import Release, SubmissionFormat, ReleaseStatus
    from models.scan import Scan, ScanStatus, ScanGrade

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB).")

    filename = file.filename or "bulk_registration.txt"

    # Handle PDF extraction
    if filename.lower().endswith(".pdf"):
        try:
            content = extract_text_from_pdf(content)
        except (ImportError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # Enforce scan quota
    await check_scan_limit(org)

    # Parse → validate → score
    releases    = parse_bulk_file(content)
    issues      = validate_bulk_file(releases, today=date.today())
    scan_result = score_bulk_scan(releases, issues)

    now = datetime.now(timezone.utc)

    # Build a synthetic release record to anchor the scan in DB
    first_release = releases[0] if releases else None
    release_title  = filename.removesuffix(".txt").removesuffix(".csv").removesuffix(".pdf")
    release_artist = first_release.artist if first_release else "Various Artists"
    release_upc    = first_release.ean if first_release else None

    db_release = Release(
        id=uuid.uuid4(),
        org_id=org.id,
        title=f"Bulk: {release_title}",
        artist=release_artist,
        upc=release_upc,
        submission_format=SubmissionFormat.BULK_REGISTRATION,
        status=ReleaseStatus.complete,
        metadata_={
            "bulk_registration": True,
            "total_releases": scan_result["total_releases"],
            "filename": filename,
        },
        created_at=now,
    )
    db.add(db_release)
    await db.flush()

    grade_enum = ScanGrade(scan_result["grade"])
    db_scan = Scan(
        id=uuid.uuid4(),
        release_id=db_release.id,
        org_id=org.id,
        status=ScanStatus.complete,
        readiness_score=scan_result["score"],
        grade=grade_enum,
        total_issues=scan_result["total_issues"],
        critical_count=scan_result["critical_count"],
        warning_count=scan_result["warning_count"],
        info_count=scan_result["info_count"],
        layers_run=["bulk_registration"],
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    # Store bulk result in validated_fields — avoids FK constraint on rules.id
    # (ScanResult rows require rule_id to exist in the rules table)
    db_scan.validated_fields = {
        "bulk_registration": True,
        "cross_release_issues": scan_result["cross_release_issues"],
        "per_release_issues": scan_result["per_release_issues"],
    }
    db.add(db_scan)

    await db.commit()

    return JSONResponse(content={
        "scan_id": str(db_scan.id),
        "release_id": str(db_release.id),
        "format": "bulk_registration",
        "status": "complete",
        "readiness_score": scan_result["score"],
        "grade": scan_result["grade"],
        "total_releases": scan_result["total_releases"],
        "releases_with_issues": scan_result["releases_with_issues"],
        "critical_count": scan_result["critical_count"],
        "warning_count": scan_result["warning_count"],
        "info_count": scan_result["info_count"],
        "total_issues": scan_result["total_issues"],
        "cross_release_issues": scan_result["cross_release_issues"],
        "per_release_issues": scan_result["per_release_issues"],
        "completed_at": now.isoformat(),
    })


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
# GET /scans — all scans for this org (pipeline view), newest first
# ──────────────────────────────────────────────────────────────────────────────

class ScanWithRelease(ScanHistoryRead):
    release_title: str = ""
    release_artist: str = ""


@router.get("/scans", response_model=list[ScanWithRelease])
async def list_org_scans(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
    limit: int = Query(50, ge=1, le=200),
):
    """Return recent scans across all releases for the org, newest first."""
    rows = await db.execute(
        text("""
            SELECT
                s.id, s.release_id, s.org_id, s.status, s.readiness_score,
                s.grade, s.total_issues, s.critical_count, s.warning_count,
                s.info_count, s.layers_run, s.started_at, s.completed_at,
                s.created_at,
                r.title AS release_title,
                r.artist AS release_artist
            FROM scans s
            JOIN releases r ON r.id = s.release_id
            WHERE s.org_id = :org_id
            ORDER BY s.created_at DESC
            LIMIT :limit
        """),
        {"org_id": str(org.id), "limit": limit},
    )
    return [ScanWithRelease.model_validate(dict(row)) for row in rows.mappings().all()]


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
# GET /scans/stats — dashboard summary (Clerk JWT auth)
# MUST be defined before /scans/{scan_id} so "stats" isn't consumed as a path param
# ──────────────────────────────────────────────────────────────────────────────

class TopIssueOut(BaseModel):
    rule_id: str
    layer: str
    severity: str
    count: int


class TrendPoint(BaseModel):
    date: str       # "Apr 15"
    critical: int
    warning: int
    info: int


class DashboardStats(BaseModel):
    critical_issues: int
    scans_this_month: int
    top_issues: list[TopIssueOut]
    trend: list[TrendPoint]   # 30 days, oldest → newest


@router.get("/scans/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Dashboard summary for the org: top issues, 30-day severity trend,
    critical issue count, and scans-this-month count.
    All data scoped to the authenticated org.
    """
    org_id = org.id
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=29)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── Top 5 issues (all time, non-pass results) ─────────────────────────────
    top_rows = await db.execute(
        text("""
            SELECT sr.rule_id, sr.layer, sr.severity, COUNT(*) AS cnt
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE s.org_id = :org_id
              AND sr.status != 'pass'
              AND sr.severity IN ('critical', 'warning')
            GROUP BY sr.rule_id, sr.layer, sr.severity
            ORDER BY cnt DESC
            LIMIT 5
        """),
        {"org_id": str(org_id)},
    )
    top_issues = [
        TopIssueOut(rule_id=r.rule_id, layer=r.layer, severity=r.severity, count=r.cnt)
        for r in top_rows.fetchall()
    ]

    # ── 30-day daily severity trend ───────────────────────────────────────────
    trend_rows = await db.execute(
        text("""
            SELECT
                DATE(sr.created_at AT TIME ZONE 'UTC') AS day,
                SUM(CASE WHEN sr.severity = 'critical' THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN sr.severity = 'warning'  THEN 1 ELSE 0 END) AS warning,
                SUM(CASE WHEN sr.severity = 'info'     THEN 1 ELSE 0 END) AS info
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE s.org_id = :org_id
              AND sr.created_at >= :since
            GROUP BY DATE(sr.created_at AT TIME ZONE 'UTC')
            ORDER BY day ASC
        """),
        {"org_id": str(org_id), "since": thirty_days_ago},
    )
    # Build a dense 30-day series (fill missing days with zeros)
    trend_map: dict[str, dict] = {}
    for row in trend_rows.fetchall():
        key = row.day.strftime("%Y-%m-%d")
        trend_map[key] = {
            "critical": int(row.critical),
            "warning": int(row.warning),
            "info": int(row.info),
        }
    trend: list[TrendPoint] = []
    for offset in range(30):
        day = (thirty_days_ago + timedelta(days=offset)).date()
        key = day.strftime("%Y-%m-%d")
        counts = trend_map.get(key, {"critical": 0, "warning": 0, "info": 0})
        trend.append(TrendPoint(
            date=day.strftime("%-m/%-d"),
            **counts,
        ))

    # ── Critical issues count (open, unresolved) ──────────────────────────────
    crit_row = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE s.org_id = :org_id
              AND sr.severity = 'critical'
              AND sr.resolved = FALSE
              AND sr.status != 'pass'
        """),
        {"org_id": str(org_id)},
    )
    critical_issues = crit_row.scalar() or 0

    # ── Scans this calendar month ─────────────────────────────────────────────
    month_row = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM scans
            WHERE org_id = :org_id
              AND created_at >= :month_start
        """),
        {"org_id": str(org_id), "month_start": month_start},
    )
    scans_this_month = month_row.scalar() or 0

    return DashboardStats(
        critical_issues=critical_issues,
        scans_this_month=scans_this_month,
        top_issues=top_issues,
        trend=trend,
    )


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
        "validated_fields": scan.validated_fields or [],
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

@router.get("/scans/{scan_id}/report")
async def get_scan_report(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Generate and stream a PDF report for the scan on-demand.

    Returns the PDF bytes directly as application/pdf with a Content-Disposition
    attachment header — no S3 or Celery required.
    """
    from models.release import Release
    from models.scan_result import ScanResult
    from services.reports.generator import ReportData, ReportGenerator, ReportIssue, ReportSuggestion
    from services.scan_orchestrator import calculate_readiness_score
    from services.audio.thresholds import DSP_THRESHOLDS

    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")

    if scan.status != "complete":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Scan is not yet complete.",
        )

    # Fetch release
    release_result = await db.execute(
        select(Release).where(Release.id == scan.release_id)
    )
    release = release_result.scalar_one_or_none()
    if not release:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Release not found")

    # Fetch all scan results
    results_query = await db.execute(
        select(ScanResult)
        .where(ScanResult.scan_id == uuid.UUID(scan_id))
        .order_by(ScanResult.severity, ScanResult.layer)
    )
    all_results = list(results_query.scalars().all())

    # Build issues + suggestions
    issues: list[ReportIssue] = []
    suggestions: list[ReportSuggestion] = []
    for r in all_results:
        if r.status == "pass":
            continue
        if r.layer == "enrichment":
            meta = r.metadata_ or {}
            suggestions.append(ReportSuggestion(
                field=r.rule_id.rsplit(".", 1)[-1],
                message=r.message,
                fix_hint=r.fix_hint,
                confidence=meta.get("confidence", "medium"),
                source_url=meta.get("source_url", ""),
            ))
        else:
            issues.append(ReportIssue(
                rule_id=r.rule_id,
                layer=r.layer,
                severity=r.severity,
                message=r.message,
                fix_hint=r.fix_hint,
                actual_value=r.actual_value,
                field_path=r.field_path,
                dsp_targets=list(r.dsp_targets or []),
                resolved=r.resolved,
            ))

    # Per-layer scores
    layer_order = ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"]
    layer_scores: dict[str, float] = {}
    for layer in layer_order:
        layer_issues = [r for r in all_results if r.layer == layer]
        layer_scores[layer] = calculate_readiness_score(layer_issues)["readiness_score"] if layer_issues else 100.0

    # DSP readiness
    dsp_readiness: dict[str, str] = {}
    for dsp_slug in DSP_THRESHOLDS.keys():
        has_blocking = any(
            r.severity == "critical" and not r.resolved and dsp_slug in (r.dsp_targets or [])
            for r in all_results
        )
        dsp_readiness[dsp_slug] = "issues" if has_blocking else "ready"
    if any(r.severity == "critical" and not r.resolved and not r.dsp_targets for r in all_results):
        for dsp_slug in dsp_readiness:
            dsp_readiness[dsp_slug] = "issues"

    md = release.metadata_ or {}
    report_data = ReportData(
        release_title=release.title,
        release_artist=release.artist,
        release_upc=release.upc,
        release_date=str(release.release_date) if release.release_date else None,
        scan_id=scan_id,
        scan_date=scan.completed_at or scan.created_at,
        org_name=md.get("org_name", ""),
        readiness_score=scan.readiness_score or 0.0,
        grade=scan.grade.value if scan.grade else "FAIL",
        critical_count=scan.critical_count,
        warning_count=scan.warning_count,
        info_count=scan.info_count,
        layer_scores=layer_scores,
        dsp_readiness=dsp_readiness,
        issues=issues,
        suggestions=suggestions,
    )

    pdf_bytes = ReportGenerator().build(report_data)

    safe_title = re.sub(r"[^\w\-]", "_", release.title)[:60]
    date_str = (scan.completed_at or scan.created_at).strftime("%Y-%m-%d")
    filename = f"SONGGATE_{safe_title}_{date_str}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /scans/{scan_id}/export/csv
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/scans/{scan_id}/export/csv")
async def export_scan_csv(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Export scan results as a flat CSV file.

    Columns: rule_id, layer, severity, message, fix_hint, dsp_targets, resolved
    """
    import csv as csv_mod

    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.status != "complete":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Scan is not complete.")

    release_result = await db.execute(select(Release).where(Release.id == scan.release_id))
    release = release_result.scalar_one_or_none()

    results_query = await db.execute(
        select(ScanResult)
        .where(ScanResult.scan_id == uuid.UUID(scan_id))
        .order_by(ScanResult.severity, ScanResult.layer)
    )
    all_results = list(results_query.scalars().all())

    output = io.StringIO()
    writer = csv_mod.writer(output)
    writer.writerow(["rule_id", "layer", "severity", "message", "fix_hint", "dsp_targets", "resolved"])
    for r in all_results:
        if r.status == "pass":
            continue
        writer.writerow([
            r.rule_id,
            r.layer,
            r.severity,
            r.message,
            r.fix_hint or "",
            ",".join(r.dsp_targets or []),
            "yes" if r.resolved else "no",
        ])

    safe_title = re.sub(r"[^\w\-]", "_", release.title if release else "scan")[:60]
    date_str = (scan.completed_at or scan.created_at).strftime("%Y-%m-%d")
    filename = f"SONGGATE_{safe_title}_{date_str}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /scans/{scan_id}/export/json
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/scans/{scan_id}/export/json")
async def export_scan_json(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Export full scan result as a JSON file.
    """
    import json as json_mod

    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.status != "complete":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Scan is not complete.")

    release_result = await db.execute(select(Release).where(Release.id == scan.release_id))
    release = release_result.scalar_one_or_none()

    results_query = await db.execute(
        select(ScanResult)
        .where(ScanResult.scan_id == uuid.UUID(scan_id))
        .order_by(ScanResult.severity, ScanResult.layer)
    )
    all_results = list(results_query.scalars().all())

    payload = {
        "scan_id": scan_id,
        "release_title": release.title if release else "",
        "release_artist": release.artist if release else "",
        "upc": release.upc if release else "",
        "readiness_score": scan.readiness_score,
        "grade": scan.grade.value if scan.grade else "FAIL",
        "critical_count": scan.critical_count,
        "warning_count": scan.warning_count,
        "info_count": scan.info_count,
        "completed_at": (scan.completed_at or scan.created_at).isoformat(),
        "results": [
            {
                "rule_id": r.rule_id,
                "layer": r.layer,
                "severity": r.severity,
                "message": r.message,
                "fix_hint": r.fix_hint,
                "actual_value": r.actual_value,
                "field_path": r.field_path,
                "dsp_targets": list(r.dsp_targets or []),
                "resolved": r.resolved,
            }
            for r in all_results
            if r.status != "pass"
        ],
    }

    safe_title = re.sub(r"[^\w\-]", "_", release.title if release else "scan")[:60]
    date_str = (scan.completed_at or scan.created_at).strftime("%Y-%m-%d")
    filename = f"SONGGATE_{safe_title}_{date_str}.json"

    return StreamingResponse(
        io.BytesIO(json_mod.dumps(payload, indent=2).encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    """Alias — report is generated on-demand, so this is a no-op that returns 202."""
    scan = await _get_scan_for_org(db, scan_id, org.id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.status != "complete":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Scan is not complete.")
    return {"detail": "Use GET /scans/{scan_id}/report to download the PDF.", "scan_id": scan_id}


# ──────────────────────────────────────────────────────────────────────────────
# GET /analytics/overview — full analytics payload, Clerk JWT auth, no tier gate
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/analytics/overview")
async def get_analytics_overview(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Same data as /api/v1/analytics/overview but authenticated with a Clerk
    session token rather than an API key, and with no Enterprise tier gate.
    Used by the internal dashboard.
    """
    from routers.public_api import _compute_analytics_overview
    return await _compute_analytics_overview(db, org.id)


@router.post("/analytics/overview/refresh")
async def refresh_analytics_overview(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    from routers.public_api import _compute_analytics_overview
    return await _compute_analytics_overview(db, org.id)


@router.post("/analytics/share", status_code=201)
async def create_share_link_clerk(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Create a public share link using Clerk JWT auth (same as /api/v1/analytics/share)."""
    from routers.public_api import _compute_analytics_overview, _sanitize_overview, _share_token_upsert, _SHARE_TTL
    import secrets
    import json
    from datetime import timedelta

    overview = await _compute_analytics_overview(db, org.id)
    token = secrets.token_urlsafe(24)
    sanitized = _sanitize_overview(overview)
    serialized = json.dumps(sanitized)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_SHARE_TTL)
    await _share_token_upsert(db, token, serialized, expires_at)
    return {"token": token, "expires_at": expires_at}


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
