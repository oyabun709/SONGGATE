"""
Celery task: per-track audio quality analysis.

Triggered by the pipeline task after tracks are parsed from the DDEX package.
Runs the full AudioAnalyzer pipeline, persists results to Track.metadata_,
then creates ScanResult rows for the audio layer.

Retry policy
────────────
  max_retries = 3
  backoff     = exponential (2^retry_count × 30 s)
  Retryable:  network errors, transient S3 failures
  Not retried: corrupted audio (ffprobe can't read it), missing track
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from celery import Task
from sqlalchemy import select

from database import AsyncSessionLocal
from models.scan import Scan, ScanStatus
from models.scan_result import ScanResult, ResultStatus
from models.track import Track
from services.audio.analyzer import AudioAnalyzer
from services.audio.thresholds import DSP_THRESHOLDS, check_against_threshold
from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Shared analyzer instance (one per worker process)
# ──────────────────────────────────────────────────────────────────────────────

_analyzer: AudioAnalyzer | None = None


def _get_analyzer() -> AudioAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = AudioAnalyzer()
    return _analyzer


# ──────────────────────────────────────────────────────────────────────────────
# Celery task
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="analyze_audio",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    track_started=True,
)
def analyze_audio_task(
    self: Task,
    track_id: str,
    scan_id: str | None = None,
    dsps: list[str] | None = None,
) -> dict:
    """
    Run audio quality analysis on a single track and persist results.

    Args:
        track_id:  UUID of the Track row that has audio_url set.
        scan_id:   Optional Scan UUID — if provided, ScanResult rows are
                   created for the audio layer under this scan.
        dsps:      DSP slugs to check thresholds against.
                   Defaults to all five primary DSPs.

    Returns:
        Dict with keys: track_id, succeeded, issues_found, errors.
    """
    if dsps is None:
        dsps = list(DSP_THRESHOLDS.keys())

    try:
        return asyncio.run(_run_analysis(track_id, scan_id, dsps))
    except Exception as exc:
        logger.exception("analyze_audio_task failed for track %s: %s", track_id, exc)
        # Retry on network/transient errors
        if _is_retryable(exc):
            raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
        return {
            "track_id": track_id,
            "succeeded": False,
            "issues_found": 0,
            "errors": [str(exc)],
        }


async def _run_analysis(
    track_id: str,
    scan_id: str | None,
    dsps: list[str],
) -> dict:
    """Async implementation — called via asyncio.run() from the Celery task."""
    async with AsyncSessionLocal() as db:
        # Fetch track
        result = await db.execute(
            select(Track).where(Track.id == uuid.UUID(track_id))
        )
        track = result.scalar_one_or_none()
        if track is None:
            logger.warning("analyze_audio_task: track %s not found", track_id)
            return {"track_id": track_id, "succeeded": False, "issues_found": 0, "errors": ["track not found"]}

        audio_url = track.audio_url
        if not audio_url:
            return {"track_id": track_id, "succeeded": False, "issues_found": 0, "errors": ["audio_url not set"]}

        # Run analysis (blocking — this is in a Celery worker, not async)
        # We run the synchronous analyzer in a thread pool to avoid blocking the
        # event loop while waiting for ffmpeg subprocesses.
        import concurrent.futures
        loop = asyncio.get_event_loop()
        analyzer = _get_analyzer()
        analysis = await loop.run_in_executor(
            None,
            lambda: analyzer.analyze(audio_url=audio_url, track_id=track_id),
        )

        # Persist analysis results to Track.metadata_
        audio_meta = analysis.to_dict()
        track.metadata_ = {**track.metadata_, "audio_analysis": audio_meta}

        # Update Track fingerprint if we got one
        if analysis.acoustid_fingerprint:
            track.acoustid_fingerprint = analysis.acoustid_fingerprint

        # Update Track duration if not already set
        if analysis.duration_seconds and not track.duration_ms:
            track.duration_ms = int(analysis.duration_seconds * 1000)

        # Create ScanResult rows for the audio layer
        issues_created = 0
        if scan_id:
            issues_created = await _create_audio_scan_results(
                db=db,
                track=track,
                analysis=analysis,
                scan_id=scan_id,
                dsps=dsps,
            )

        await db.commit()

        return {
            "track_id": track_id,
            "succeeded": analysis.succeeded,
            "issues_found": issues_created,
            "errors": analysis.errors,
            "format": analysis.format,
            "sample_rate": analysis.sample_rate,
            "integrated_lufs": analysis.integrated_lufs,
            "true_peak_dbtp": analysis.true_peak_dbtp,
        }


async def _create_audio_scan_results(
    db,
    track: Track,
    analysis,
    scan_id: str,
    dsps: list[str],
) -> int:
    """
    Convert AudioAnalysisResult + DSP threshold checks into ScanResult rows.

    Returns the number of non-passing results created.
    """
    now = datetime.now(timezone.utc)
    scan_uuid = uuid.UUID(scan_id)
    issues = 0

    # Cross-check against each DSP threshold
    all_findings: dict[str, list[dict]] = {}
    for dsp_slug in dsps:
        threshold = DSP_THRESHOLDS.get(dsp_slug)
        if threshold is None:
            continue
        findings = check_against_threshold(analysis, threshold)
        for f in findings:
            rule_id = f["rule_id"]
            if rule_id not in all_findings:
                all_findings[rule_id] = []
            all_findings[rule_id].append({"dsp": dsp_slug, **f})

    for rule_id, dsp_findings in all_findings.items():
        # Collect all DSPs that flagged this rule
        dsp_targets = [f["dsp"] for f in dsp_findings]
        # Use the highest severity across DSPs
        severity = _highest_severity([f["severity"] for f in dsp_findings])
        first = dsp_findings[0]

        scan_result = ScanResult(
            id=uuid.uuid4(),
            scan_id=scan_uuid,
            track_id=track.id,
            layer="audio",
            rule_id=rule_id,
            severity=severity,
            status=ResultStatus.fail,
            message=first["message"],
            fix_hint=first.get("fix_hint"),
            actual_value=first.get("actual_value"),
            dsp_targets=dsp_targets,
            metadata_={"analysis": analysis.to_dict()},
            created_at=now,
        )
        db.add(scan_result)
        issues += 1

    # Global issues: clipping, silence
    if analysis.is_clipping:
        db.add(ScanResult(
            id=uuid.uuid4(),
            scan_id=scan_uuid,
            track_id=track.id,
            layer="audio",
            rule_id="universal.audio.true_peak_clipping",
            severity="critical",
            status=ResultStatus.fail,
            message=(
                f"True peak {analysis.true_peak_dbtp:.2f} dBTP exceeds "
                f"the −1 dBTP ceiling. Clipping detected."
            ),
            fix_hint="Apply true-peak limiting to −1 dBTP before delivery.",
            actual_value=f"{analysis.true_peak_dbtp:.2f} dBTP" if analysis.true_peak_dbtp else None,
            dsp_targets=dsps,
            metadata_={},
            created_at=now,
        ))
        issues += 1

    if analysis.has_leading_silence:
        db.add(ScanResult(
            id=uuid.uuid4(),
            scan_id=scan_uuid,
            track_id=track.id,
            layer="audio",
            rule_id="universal.audio.silence_at_start",
            severity="info",
            status=ResultStatus.warn,
            message=f"Track has more than {AudioAnalyzer.SILENCE_MIN_DURATION}s of silence at the start.",
            fix_hint="Trim leading silence from the audio file.",
            dsp_targets=dsps,
            metadata_={},
            created_at=now,
        ))

    if analysis.has_trailing_silence:
        db.add(ScanResult(
            id=uuid.uuid4(),
            scan_id=scan_uuid,
            track_id=track.id,
            layer="audio",
            rule_id="universal.audio.silence_at_end",
            severity="info",
            status=ResultStatus.warn,
            message=f"Track has more than {AudioAnalyzer.SILENCE_MIN_DURATION}s of silence at the end.",
            fix_hint="Trim trailing silence from the audio file.",
            dsp_targets=dsps,
            metadata_={},
            created_at=now,
        ))

    return issues


def _highest_severity(severities: list[str]) -> str:
    order = {"critical": 3, "warning": 2, "info": 1}
    return max(severities, key=lambda s: order.get(s, 0), default="info")


def _is_retryable(exc: Exception) -> bool:
    """True for transient errors worth retrying."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    retryable_signals = (
        "connectionerror", "timeout", "temporaryerror",
        "throttling", "slowdown", "503", "502", "429",
    )
    return any(s in name or s in msg for s in retryable_signals)
