"""
Celery task: generate a PDF scan report and upload it to S3.

Triggered by the scan orchestrator after a scan completes.
Stores the S3 key on Scan.report_url and sets Scan.report_generated_at.

Retry policy
────────────
  max_retries = 3
  backoff     = exponential (60 s × 2^retry_count)
  Retryable:  S3 upload errors, DB connection drops
  Not retried: missing scan, PDF generation failures (logged only)
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import uuid
from datetime import datetime, timezone

import boto3
from celery import Task
from sqlalchemy import select

from database import AsyncSessionLocal
from models.release import Release
from models.scan import Scan
from models.scan_result import ScanResult, ResultStatus
from services.reports.generator import (
    ReportData,
    ReportGenerator,
    ReportIssue,
    ReportSuggestion,
)
from services.scan_orchestrator import calculate_readiness_score
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# S3 folder for reports
_REPORTS_PREFIX = "ropqa/{org_id}/releases/{release_id}/reports"


@celery_app.task(
    bind=True,
    name="generate_report",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    track_started=True,
)
def generate_report_task(self: Task, scan_id: str) -> dict:
    """
    Generate a PDF report for a completed scan and upload it to S3.

    Args:
        scan_id: UUID of the Scan row to report on.

    Returns:
        Dict with keys: scan_id, report_url, succeeded.
    """
    try:
        return asyncio.run(_run_generate(scan_id))
    except Exception as exc:
        logger.exception("generate_report_task failed for scan %s: %s", scan_id, exc)
        if _is_retryable(exc):
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        return {"scan_id": scan_id, "report_url": None, "succeeded": False}


async def _run_generate(scan_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        # ── Fetch scan + release ───────────────────────────────────────────
        scan_result = await db.execute(
            select(Scan).where(Scan.id == uuid.UUID(scan_id))
        )
        scan = scan_result.scalar_one_or_none()
        if scan is None:
            logger.warning("generate_report: scan %s not found", scan_id)
            return {"scan_id": scan_id, "report_url": None, "succeeded": False}

        release_result = await db.execute(
            select(Release).where(Release.id == scan.release_id)
        )
        release = release_result.scalar_one_or_none()
        if release is None:
            logger.warning("generate_report: release for scan %s not found", scan_id)
            return {"scan_id": scan_id, "report_url": None, "succeeded": False}

        # ── Fetch all scan results ─────────────────────────────────────────
        results_query = await db.execute(
            select(ScanResult)
            .where(ScanResult.scan_id == uuid.UUID(scan_id))
            .order_by(ScanResult.severity, ScanResult.layer)
        )
        all_results = list(results_query.scalars().all())

        # ── Build ReportData ───────────────────────────────────────────────
        report_data = _build_report_data(scan, release, all_results)

        # ── Generate PDF ───────────────────────────────────────────────────
        generator = ReportGenerator()
        pdf_bytes = generator.build(report_data)

        # ── Upload to S3 ───────────────────────────────────────────────────
        s3_key = _make_s3_key(release, scan)
        report_url = await _upload_to_s3(pdf_bytes, s3_key, str(scan.org_id))

        # ── Persist URL on Scan ────────────────────────────────────────────
        scan.report_url = report_url
        scan.report_generated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info("Report generated for scan %s → %s", scan_id, report_url)
        return {"scan_id": scan_id, "report_url": report_url, "succeeded": True}


def _build_report_data(
    scan: Scan,
    release: Release,
    all_results: list[ScanResult],
) -> ReportData:
    """Assemble ReportData from DB rows."""
    from services.audio.thresholds import DSP_THRESHOLDS

    # Separate issues from enrichment suggestions
    issues: list[ReportIssue] = []
    suggestions: list[ReportSuggestion] = []

    for r in all_results:
        if r.status == ResultStatus.pass_:
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
    from services.scan_orchestrator import calculate_readiness_score
    layer_order = ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"]
    layer_scores: dict[str, float] = {}
    for layer in layer_order:
        layer_issues = [r for r in all_results if r.layer == layer]
        if layer_issues:
            sd = calculate_readiness_score(layer_issues)
            layer_scores[layer] = sd["readiness_score"]
        else:
            layer_scores[layer] = 100.0

    # DSP readiness: check if any critical, non-resolved result targets each DSP
    dsp_readiness: dict[str, str] = {}
    for dsp_slug in DSP_THRESHOLDS.keys():
        has_blocking = any(
            r.severity == "critical" and not r.resolved
            and dsp_slug in (r.dsp_targets or [])
            for r in all_results
        )
        dsp_readiness[dsp_slug] = "issues" if has_blocking else "ready"

    # Also mark DSPs with no dsp_targets critical issues as ready
    # (universal critical issues affect all DSPs)
    universal_critical = any(
        r.severity == "critical" and not r.resolved
        and (not r.dsp_targets)
        for r in all_results
    )
    if universal_critical:
        for dsp_slug in dsp_readiness:
            dsp_readiness[dsp_slug] = "issues"

    md = release.metadata_ or {}
    org_name = md.get("org_name", "")

    return ReportData(
        release_title=release.title,
        release_artist=release.artist,
        release_upc=release.upc,
        release_date=str(release.release_date) if release.release_date else None,
        scan_id=str(scan.id),
        scan_date=scan.completed_at or scan.created_at,
        org_name=org_name,
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


def _make_s3_key(release: Release, scan: Scan) -> str:
    """Build the S3 object key for the report PDF."""
    safe_title = re.sub(r"[^\w\-]", "_", release.title)[:60]
    date_str = (scan.completed_at or scan.created_at).strftime("%Y-%m-%d")
    filename = f"ROPQA_{safe_title}_{date_str}.pdf"
    prefix = _REPORTS_PREFIX.format(
        org_id=scan.org_id,
        release_id=release.id,
    )
    return f"{prefix}/{filename}"


async def _upload_to_s3(pdf_bytes: bytes, s3_key: str, org_id: str) -> str:
    """Upload PDF bytes to S3 and return the object key (not presigned URL)."""
    from config import settings

    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url

    s3 = boto3.client("s3", **kwargs)

    # Run blocking boto3 call in thread pool so we don't block the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: s3.put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
            ContentDisposition=f'attachment; filename="{s3_key.rsplit("/", 1)[-1]}"',
        ),
    )
    return s3_key  # store key; presigned URL generated at download time


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    signals = ("connectionerror", "timeout", "throttling", "slowdown", "503", "502", "429")
    return any(s in name or s in msg for s in signals)
