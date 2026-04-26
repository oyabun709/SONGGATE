"""
Scan orchestration service.

Runs all 5 QA layers for a release scan in the correct order, persists
ScanResult rows, calculates the readiness score, and fires async tasks
for audio analysis and report generation.

Layer execution order
─────────────────────
1. DDEX / CSV / JSON validation  (sync, fast ~100 ms)
2. DSP metadata rules engine     (sync, fast ~50 ms)
3. Fraud pre-screening           (sync, DB-query backed ~200 ms)
4. Audio QA                      (Celery task — fire and forget)
5. Artwork validation            (blocking I/O in thread pool ~2–5 s)
6. MusicBrainz enrichment        (blocking network in thread pool ~1–3 s)

Score formula
─────────────
  Start:    100 points
  Critical: −10 pts each  (total cap: −60)
  Warning:  −3 pts each   (total cap: −25)
  Info:     −0.5 pts each (total cap: −5)
  Clamp to [0, 100]

  Grade:  ≥ 80 → PASS  |  60–79 → WARN  |  < 60 → FAIL
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.release import Release, ReleaseStatus
from models.rule import Rule
from models.scan import Scan, ScanGrade, ScanStatus
from models.scan_result import ScanResult, ResultStatus
from models.track import Track
from services.artwork.validator import ArtworkValidator, ArtworkFinding
from services.ddex.validator import DDEXValidator, DDEXFinding
from services.enrichment.musicbrainz import MusicBrainzEnricher, EnrichmentSuggestion
from services.fraud.screener import FraudScreener, FraudSignal, VelocityContext
from services.metadata.rules_engine import DSPRulesEngine, ReleaseMetadata, RuleResult

logger = logging.getLogger(__name__)

_ALL_LAYERS = ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"]

# ──────────────────────────────────────────────────────────────────────────────
# Score calculation
# ──────────────────────────────────────────────────────────────────────────────

def deduplicate_cross_layer(results: list[ScanResult]) -> list[ScanResult]:
    """
    Remove ScanResult rows that duplicate what a more specific layer already caught.
    Mirrors the same logic in the demo endpoint.

    Rules:
      1. Artwork layer has a finding → drop metadata artwork-dimension rules
      2. DDEX has an ISRC format error → drop metadata generic ISRC-format rule
      3. DDEX has a missing-publisher finding → drop metadata publisher-required rule
      4. Metadata warned about a short track by name → drop fraud short-track signal
    """
    has_artwork = any(r.layer == "artwork" for r in results)
    ddex_isrc_error = any(
        r.layer == "ddex" and "isrc" in (r.message or "").lower() for r in results
    )
    ddex_publisher_error = any(
        r.layer == "ddex" and "publisher" in (r.message or "").lower() for r in results
    )
    meta_short_titles: set[str] = set()
    for r in results:
        if r.layer == "metadata" and " seconds" in (r.message or ""):
            msg = r.message or ""
            if msg.startswith('"'):
                try:
                    meta_short_titles.add(msg[1: msg.index('"', 1)].lower())
                except ValueError:
                    pass

    deduped: list[ScanResult] = []
    for r in results:
        msg = (r.message or "").lower()
        rule = (r.rule_id or "").lower()

        if has_artwork and r.layer == "metadata":
            if "artwork" in msg or "artwork" in rule:
                continue

        if ddex_isrc_error and r.layer == "metadata":
            if "iso 3901" in msg or "isrc must follow" in msg:
                continue

        if ddex_publisher_error and r.layer == "metadata":
            if "publisher" in msg and ("required" in msg or "rights holder" in msg):
                continue

        if meta_short_titles and r.layer == "fraud":
            if "under 60 seconds" in msg or "sub-60" in msg:
                if any(t in msg for t in meta_short_titles):
                    continue

        deduped.append(r)

    return deduped


def calculate_readiness_score(results: list[ScanResult]) -> dict[str, Any]:
    """
    Aggregate ScanResult rows into a readiness score and grade.

    Only unresolved non-pass results contribute to deductions.
    Enrichment suggestions (info severity, enrichment layer) are excluded
    from score deductions — they are advisory only.
    """
    critical = 0
    warnings = 0
    info = 0

    for r in results:
        if r.resolved or r.status == ResultStatus.pass_:
            continue
        if r.layer == "enrichment":
            continue   # enrichment suggestions don't deduct points
        if r.severity == "critical":
            critical += 1
        elif r.severity == "warning":
            warnings += 1
        else:
            info += 1

    deductions = (
        min(critical * 10.0, 60.0)
        + min(warnings * 3.0, 25.0)
        + min(info * 0.5, 5.0)
    )
    score = round(max(0.0, 100.0 - deductions), 1)

    if score >= 80:
        grade = ScanGrade.PASS
    elif score >= 60:
        grade = ScanGrade.WARN
    else:
        grade = ScanGrade.FAIL

    return {
        "readiness_score": score,
        "grade": grade,
        "total_issues": critical + warnings + info,
        "critical_count": critical,
        "warning_count": warnings,
        "info_count": info,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class ScanOrchestrator:
    """
    Runs all QA layers for a release scan and persists results to the DB.

    Usage::

        orchestrator = ScanOrchestrator()
        scan = await orchestrator.run_scan(
            release_id="...",
            scan_id="...",
            org_id="...",
            dsps=["spotify", "apple"],
            layers=None,   # None = all layers
        )
    """

    def __init__(self) -> None:
        self.ddex_validator = DDEXValidator()
        self.rules_engine = DSPRulesEngine()
        self.fraud_screener = FraudScreener()
        self.artwork_validator = ArtworkValidator()
        self.enricher = MusicBrainzEnricher()

    async def run_scan(
        self,
        release_id: str,
        scan_id: str,
        org_id: str,
        dsps: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> Scan:
        """
        Execute the full scan pipeline and return the updated Scan row.

        Fires the audio analysis Celery task asynchronously (does not wait).
        All other layers complete synchronously before this method returns.
        """
        if dsps is None:
            from services.audio.thresholds import DSP_THRESHOLDS
            dsps = list(DSP_THRESHOLDS.keys())

        async with AsyncSessionLocal() as db:
            # ── Fetch release + org ────────────────────────────────────────
            release = await self._fetch_release(db, release_id, org_id)
            if release is None:
                raise ValueError(f"Release {release_id} not found for org {org_id}")

            scan = await self._fetch_scan(db, scan_id)
            if scan is None:
                raise ValueError(f"Scan {scan_id} not found")

            # Intersect requested layers with org's tier-permitted layers
            from sqlalchemy import select as sa_select
            from models.organization import Organization
            org_row = await db.scalar(
                sa_select(Organization).where(Organization.id == uuid.UUID(org_id))
            )
            allowed = set(org_row.allowed_layers) if org_row else set(_ALL_LAYERS)
            requested = set(layers or _ALL_LAYERS)
            active_layers = requested & allowed

            # ── Increment scan counter ─────────────────────────────────────
            if org_row:
                org_row.scan_count_current_period = (
                    org_row.scan_count_current_period or 0
                ) + 1
                # Report to Stripe (no-op for Starter flat-rate)
                try:
                    from services.billing import report_usage
                    await report_usage(org_row, quantity=1)
                except Exception:
                    logger.warning("Could not report usage to Stripe for org %s", org_id)

            # ── Mark running ───────────────────────────────────────────────
            scan.status = ScanStatus.running
            scan.started_at = datetime.now(timezone.utc)
            scan.layers_run = list(active_layers)
            release.status = ReleaseStatus.scanning
            await db.commit()

            all_results: list[ScanResult] = []
            errors: list[str] = []

            try:
                # ── Layer 1: DDEX / format validation ─────────────────────
                if "ddex" in active_layers:
                    ddex_results = await self._run_ddex_layer(db, release, scan_id)
                    all_results.extend(ddex_results)

                # ── Layer 2: DSP metadata rules ────────────────────────────
                if "metadata" in active_layers:
                    metadata_results = await self._run_metadata_layer(db, release, scan_id, dsps)
                    all_results.extend(metadata_results)

                # ── Layer 3: Fraud screening ───────────────────────────────
                if "fraud" in active_layers:
                    fraud_results = await self._run_fraud_layer(db, release, scan_id)
                    all_results.extend(fraud_results)

                # ── Layer 4: Audio QA — fire Celery task, don't wait ───────
                if "audio" in active_layers:
                    audio_results = await self._fire_audio_tasks(db, release, scan_id, dsps)
                    if audio_results:
                        all_results.extend(audio_results)

                # ── Layer 5: Artwork validation ────────────────────────────
                if "artwork" in active_layers:
                    artwork_results = await self._run_artwork_layer(db, release, scan_id)
                    all_results.extend(artwork_results)

                # ── Layer 6: MusicBrainz enrichment ───────────────────────
                if "enrichment" in active_layers:
                    enrichment_results = await self._run_enrichment_layer(db, release, scan_id)
                    all_results.extend(enrichment_results)

                # ── Persist all synchronous-layer results ──────────────────
                for sr in all_results:
                    db.add(sr)
                await db.flush()

                # ── Deduplicate cross-layer findings before scoring ────────
                all_results = deduplicate_cross_layer(all_results)

                # ── Calculate score from sync-layer results only ───────────
                # (audio results arrive later and update the scan via the task)
                score_data = calculate_readiness_score(all_results)

                scan.readiness_score = score_data["readiness_score"]
                scan.grade = score_data["grade"]
                scan.total_issues = score_data["total_issues"]
                scan.critical_count = score_data["critical_count"]
                scan.warning_count = score_data["warning_count"]
                scan.info_count = score_data["info_count"]
                scan.validated_fields = self._build_validated_fields(release)
                scan.status = ScanStatus.complete
                scan.completed_at = datetime.now(timezone.utc)

                release.status = ReleaseStatus.complete

            except Exception as exc:
                logger.exception("Scan %s failed: %s", scan_id, exc)
                errors.append(str(exc))
                scan.status = ScanStatus.failed
                scan.completed_at = datetime.now(timezone.utc)
                release.status = ReleaseStatus.failed

            await db.commit()
            await db.refresh(scan)

            # ── Fire report generation task ────────────────────────────────
            if scan.status == ScanStatus.complete:
                try:
                    self._fire_report_task(scan_id)
                except Exception:
                    pass  # Report generation is best-effort

            # ── Send email notification ────────────────────────────────────
            await self._notify(
                org_row=org_row,
                release=release,
                scan=scan,
                errors=errors,
            )

            return scan

    # ── Layer implementations ──────────────────────────────────────────────────

    async def _run_ddex_layer(
        self, db: AsyncSession, release: Release, scan_id: str
    ) -> list[ScanResult]:
        """Download the DDEX/CSV/JSON package and validate it."""
        if not release.raw_package_url:
            return []

        now = datetime.now(timezone.utc)
        scan_uuid = uuid.UUID(scan_id)

        try:
            content = await self._download_artifact(release.raw_package_url)
        except Exception as exc:
            logger.warning("DDEX layer: could not download artifact: %s", exc)
            return []

        fmt = (release.submission_format.value or "").upper()

        if "DDEX" in fmt:
            findings: list[DDEXFinding] = self.ddex_validator.validate(content)

            # Extract metadata from the DDEX package and persist it so the
            # metadata rules engine has real values to evaluate in layer 2.
            try:
                from services.ddex.validator import DDEXParser
                from datetime import date as _date
                parsed = DDEXParser().extract_metadata(content)
                if parsed and "_error" not in parsed:
                    existing = dict(release.metadata_ or {})
                    existing.update(parsed)
                    release.metadata_ = existing
                    # Promote top-level DB columns if not already set
                    if parsed.get("upc") and not release.upc:
                        release.upc = parsed["upc"]
                    if parsed.get("release_date") and not release.release_date:
                        try:
                            release.release_date = _date.fromisoformat(parsed["release_date"])
                        except (ValueError, TypeError):
                            pass
                    # Upsert Track rows so per-track endpoints work
                    from models.track import Track as TrackModel
                    from sqlalchemy import select as _sel
                    for idx, t in enumerate(parsed.get("tracks", []), start=1):
                        raw_isrc = t.get("isrc") or None
                        isrc = raw_isrc.replace("-", "")[:12] if raw_isrc else None
                        # Find existing row by ISRC or by position
                        existing_track = None
                        if isrc:
                            tr = await db.execute(
                                _sel(TrackModel).where(
                                    TrackModel.release_id == release.id,
                                    TrackModel.isrc == isrc,
                                )
                            )
                            existing_track = tr.scalar_one_or_none()
                        if not existing_track:
                            tr2 = await db.execute(
                                _sel(TrackModel).where(
                                    TrackModel.release_id == release.id,
                                    TrackModel.track_number == idx,
                                )
                            )
                            existing_track = tr2.scalar_one_or_none()
                        if existing_track:
                            existing_track.isrc = isrc
                            existing_track.title = t.get("title") or existing_track.title
                        else:
                            db.add(TrackModel(
                                id=uuid.uuid4(),
                                release_id=release.id,
                                isrc=isrc,
                                title=t.get("title") or "Unknown",
                                track_number=idx,
                                duration_ms=t.get("duration_ms"),
                            ))
                    await db.commit()
                    await db.refresh(release)
                    logger.info(
                        "DDEX layer: extracted metadata for release %s — "
                        "%d tracks, isrc_list=%s",
                        release.id,
                        len(parsed.get("tracks", [])),
                        parsed.get("isrc_list", []),
                    )
            except Exception as exc:
                logger.warning("DDEX layer: metadata extraction failed: %s", exc)
                try:
                    await db.rollback()
                except Exception:
                    pass

        elif fmt == "CSV":
            from services.ddex.csv_parser import CSVParser
            parse_result = CSVParser().parse(content)
            findings = [
                DDEXFinding(
                    rule_id=f"ddex.csv.{e.code if hasattr(e, 'code') else 'parse_error'}",
                    severity="critical",
                    message=str(e),
                    field_path=None,
                )
                for e in (parse_result.errors if hasattr(parse_result, "errors") else [])
            ]

            # Populate release.metadata_ from parsed CSV so the metadata rules
            # engine has real values instead of empty defaults.
            if parse_result.releases:
                rel = parse_result.releases[0]
                tracks = rel.get("tracks", [])
                isrc_list = [t["isrc"] for t in tracks if t.get("isrc")]
                composers = list({
                    t["composer"] for t in tracks
                    if t.get("composer")
                })
                md_update = {
                    "label":           rel.get("label") or "",
                    "release_type":    rel.get("release_type") or "",
                    "genre":           rel.get("genre") or "",
                    "parental_warning": rel.get("parental_warning") or "",
                    "c_line":          rel.get("c_line") or "",
                    "p_line":          rel.get("p_line") or "",
                    "territory":       rel.get("territory") or "Worldwide",
                    "commercial_model": rel.get("commercial_model") or "",
                    "tracks":          tracks,
                    "isrc_list":       isrc_list,
                    "composers":       composers,
                }
                existing = dict(release.metadata_ or {})
                existing.update(md_update)
                release.metadata_ = existing
                try:
                    await db.commit()
                except Exception as exc:
                    logger.warning("CSV layer: metadata commit failed: %s", exc)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
        else:
            findings = []

        results: list[ScanResult] = []
        for f in findings:
            await self._ensure_rule(db, f.rule_id, "ddex", f.severity)
            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="ddex",
                rule_id=f.rule_id,
                severity=f.severity,
                status=ResultStatus.fail,
                message=f.message,
                field_path=getattr(f, "field_path", None),
                actual_value=getattr(f, "actual_value", None),
                fix_hint=getattr(f, "fix_hint", None),
                dsp_targets=[],
                metadata_={},
                created_at=now,
            ))

        return results

    async def _run_metadata_layer(
        self, db: AsyncSession, release: Release, scan_id: str, dsps: list[str]
    ) -> list[ScanResult]:
        """Evaluate DSP metadata rules against this release."""
        now = datetime.now(timezone.utc)
        scan_uuid = uuid.UUID(scan_id)

        meta = self._build_release_metadata(release)
        rule_results: list[RuleResult] = self.rules_engine.evaluate(meta, dsps=dsps)

        results: list[ScanResult] = []
        for rr in rule_results:
            if rr.status == "pass" or rr.status == "skip":
                continue
            severity = rr.severity
            status = ResultStatus.fail if severity in ("critical",) else ResultStatus.warn
            await self._ensure_rule(db, rr.rule_id, "metadata", severity)
            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="metadata",
                rule_id=rr.rule_id,
                severity=severity,
                status=status,
                message=rr.message,
                actual_value=str(rr.checked_value) if rr.checked_value is not None else None,
                fix_hint=rr.fix_hint,
                dsp_targets=dsps,
                metadata_={},
                created_at=now,
            ))

        return results

    async def _run_fraud_layer(
        self, db: AsyncSession, release: Release, scan_id: str
    ) -> list[ScanResult]:
        """Run fraud pre-screening."""
        now = datetime.now(timezone.utc)
        scan_uuid = uuid.UUID(scan_id)

        # Load org settings to check test mode
        from sqlalchemy import select as _sa_select
        from models.organization import Organization as Org
        org_row = await db.scalar(_sa_select(Org).where(Org.id == release.org_id))
        is_test_org = bool((org_row.settings if org_row else {}).get("is_test", False))

        # Build velocity context from DB counts
        velocity = await self._build_velocity_context(db, release)

        # Build known_isrcs: {isrc: release_id} for duplicate detection
        known_isrcs = await self._fetch_known_isrcs(db, release.org_id)

        meta = self._build_release_metadata(release)
        signals: list[FraudSignal] = self.fraud_screener.screen(
            metadata=meta,
            org_id=str(release.org_id),
            velocity=velocity,
            known_isrcs=known_isrcs,
        )

        # Velocity-based signal IDs (suppressed for test orgs to avoid false positives)
        _velocity_signal_ids = {
            "fraud.high_release_velocity_artist",
            "fraud.high_release_velocity_org",
            "high_release_velocity_artist",
            "high_release_velocity_org",
        }

        results: list[ScanResult] = []
        for sig in signals:
            # signal_id already includes the "fraud." prefix (e.g. "fraud.short_track_duration")
            rule_id = sig.signal_id if sig.signal_id.startswith("fraud.") else f"fraud.{sig.signal_id}"

            # Skip velocity signals for test orgs
            if is_test_org and (rule_id in _velocity_signal_ids or sig.signal_id in _velocity_signal_ids):
                logger.debug("Skipping velocity signal %s for test org %s", rule_id, release.org_id)
                continue

            await self._ensure_rule(db, rule_id, "fraud", sig.severity)
            status = ResultStatus.warn if sig.is_advisory else ResultStatus.fail
            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="fraud",
                rule_id=rule_id,
                severity=sig.severity,
                status=status,
                message=sig.explanation,
                actual_value=sig.matched_value or None,
                fix_hint=sig.resolution,
                dsp_targets=[],
                metadata_={"confidence": sig.confidence, "category": sig.category, **sig.details},
                created_at=now,
            ))

        return results

    async def _fire_audio_tasks(
        self, db: AsyncSession, release: Release, scan_id: str, dsps: list[str]
    ) -> list[ScanResult]:
        """Inline audio analysis — no Celery, no Redis.

        Downloads each track's audio URL and analyzes it synchronously using
        mutagen (metadata) + soundfile/pyloudnorm (LUFS for lossless formats).
        Returns ScanResults immediately so they are included in the scan score.
        """
        from services.audio.inline_analyzer import analyze_track_inline

        tracks_result = await db.execute(
            select(Track).where(Track.release_id == release.id)
        )
        tracks = list(tracks_result.scalars().all())

        tracks_with_audio = [t for t in tracks if t.audio_url]
        if not tracks_with_audio:
            await self._ensure_rule(db, "audio.file.not_provided", "audio", "info")
            return [ScanResult(
                id=uuid.uuid4(),
                scan_id=uuid.UUID(scan_id),
                layer="audio",
                rule_id="audio.file.not_provided",
                severity="info",
                status=ResultStatus.warn,
                message="No audio files were uploaded — audio quality checks skipped.",
                fix_hint=(
                    "Set an audio URL per track via "
                    "POST /releases/{id}/tracks/{track_id}/audio-url "
                    "to enable loudness, duration, and codec validation."
                ),
                dsp_targets=[],
                created_at=datetime.now(timezone.utc),
            )]

        all_audio_results: list[ScanResult] = []
        for track in tracks_with_audio:
            try:
                track_results = await analyze_track_inline(
                    audio_url=track.audio_url,
                    track_id=str(track.id),
                    track_title=track.title,
                    scan_id=scan_id,
                    dsps=dsps,
                    db=db,
                )
                all_audio_results.extend(track_results)
            except Exception:
                logger.warning(
                    "Inline audio analysis failed for track %s", track.id, exc_info=True
                )

        if not all_audio_results and tracks_with_audio:
            await self._ensure_rule(db, "audio.analysis.unavailable", "audio", "info")
            all_audio_results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=uuid.UUID(scan_id),
                layer="audio",
                rule_id="audio.analysis.unavailable",
                severity="info",
                status=ResultStatus.warn,
                message="Audio analysis could not complete for any track.",
                fix_hint="Ensure audio URLs are publicly accessible and in a supported format (WAV, FLAC, MP3).",
                dsp_targets=[],
                created_at=datetime.now(timezone.utc),
            ))

        return all_audio_results

    async def _run_artwork_layer(
        self, db: AsyncSession, release: Release, scan_id: str
    ) -> list[ScanResult]:
        """Validate cover artwork."""
        artwork_url = (release.metadata_ or {}).get("artwork_url")
        if not artwork_url:
            # Fall back to first track's artwork_url
            track_result = await db.execute(
                select(Track).where(Track.release_id == release.id).limit(1)
            )
            track = track_result.scalar_one_or_none()
            if track:
                artwork_url = track.artwork_url

        if not artwork_url:
            await self._ensure_rule(db, "artwork.file.not_provided", "artwork", "info")
            return [ScanResult(
                id=uuid.uuid4(),
                scan_id=uuid.UUID(scan_id),
                layer="artwork",
                rule_id="artwork.file.not_provided",
                severity="info",
                status=ResultStatus.warn,
                message="No artwork file was uploaded — artwork dimension and format checks skipped.",
                fix_hint="Upload a minimum 3000×3000 px JPEG/PNG cover image to enable artwork validation.",
                dsp_targets=[],
                created_at=datetime.now(timezone.utc),
            )]

        now = datetime.now(timezone.utc)
        scan_uuid = uuid.UUID(scan_id)

        loop = asyncio.get_event_loop()
        try:
            analysis = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.artwork_validator.validate(artwork_url)),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Artwork layer timed out — skipping")
            return []

        results: list[ScanResult] = []
        for f in analysis.findings:
            await self._ensure_rule(db, f.rule_id, "artwork", f.severity)
            status = (
                ResultStatus.fail if f.severity == "critical"
                else ResultStatus.warn if f.severity == "warning"
                else ResultStatus.warn
            )
            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="artwork",
                rule_id=f.rule_id,
                severity=f.severity,
                status=status,
                message=f.message,
                actual_value=f.actual_value,
                fix_hint=f.fix_hint,
                dsp_targets=[],
                metadata_={
                    "artwork_url": artwork_url,
                    "width": analysis.width,
                    "height": analysis.height,
                    "format": analysis.format,
                    "color_mode": analysis.color_mode,
                },
                created_at=now,
            ))

        return results

    async def _run_enrichment_layer(
        self, db: AsyncSession, release: Release, scan_id: str
    ) -> list[ScanResult]:
        """Run MusicBrainz enrichment and surface suggestions as info results."""
        now = datetime.now(timezone.utc)
        scan_uuid = uuid.UUID(scan_id)

        meta = self._build_release_metadata(release)
        if not meta.title or not meta.artist:
            return []

        loop = asyncio.get_event_loop()
        try:
            enrichment = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.enricher.enrich_release(meta)),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Enrichment layer timed out for release %s — skipping", release.id)
            return []
        except Exception as exc:
            logger.warning("Enrichment layer failed: %s", exc)
            return []

        results: list[ScanResult] = []
        seen_rule_ids: set[str] = set()

        for suggestion in enrichment.suggestions:
            rule_id = f"enrichment.mb.{suggestion.field}"
            if rule_id in seen_rule_ids:
                continue
            seen_rule_ids.add(rule_id)

            await self._ensure_rule(db, rule_id, "enrichment", "info")
            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="enrichment",
                rule_id=rule_id,
                severity="info",
                status=ResultStatus.warn,
                message=suggestion.message,
                actual_value=suggestion.current or None,
                fix_hint=f"Suggested value from MusicBrainz: {suggestion.suggested}",
                dsp_targets=[],
                metadata_={
                    "suggested": suggestion.suggested,
                    "confidence": suggestion.confidence,
                    "source_url": suggestion.source_url,
                    "mb_entity_id": suggestion.mb_entity_id,
                },
                created_at=now,
            ))

        return results

    # ── Score update (called by audio task after it finishes) ──────────────────

    @staticmethod
    async def recalculate_scan_score(scan_id: str) -> None:
        """
        Re-run score calculation after async layers (e.g. audio) complete.

        Called by the audio analysis Celery task after it persists its results.
        """
        async with AsyncSessionLocal() as db:
            scan_result = await db.execute(
                select(Scan).where(Scan.id == uuid.UUID(scan_id))
            )
            scan = scan_result.scalar_one_or_none()
            if scan is None:
                return

            results_query = await db.execute(
                select(ScanResult).where(ScanResult.scan_id == uuid.UUID(scan_id))
            )
            all_results = list(results_query.scalars().all())

            score_data = calculate_readiness_score(all_results)
            scan.readiness_score = score_data["readiness_score"]
            scan.grade = score_data["grade"]
            scan.total_issues = score_data["total_issues"]
            scan.critical_count = score_data["critical_count"]
            scan.warning_count = score_data["warning_count"]
            scan.info_count = score_data["info_count"]

            await db.commit()

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _fetch_release(
        self, db: AsyncSession, release_id: str, org_id: str
    ) -> Release | None:
        result = await db.execute(
            select(Release).where(
                Release.id == uuid.UUID(release_id),
                Release.org_id == uuid.UUID(org_id),
            )
        )
        return result.scalar_one_or_none()

    async def _fetch_scan(self, db: AsyncSession, scan_id: str) -> Scan | None:
        result = await db.execute(
            select(Scan).where(Scan.id == uuid.UUID(scan_id))
        )
        return result.scalar_one_or_none()

    def _build_validated_fields(self, release: Release) -> list[dict]:
        """
        Build the validated_fields list that mirrors the demo's green checks view.
        Returns a list of {label, value, format} dicts for every non-empty field.
        Stored on the Scan row so the results page can render it without re-parsing.
        """
        md = release.metadata_ or {}
        tracks_data: list[dict] = md.get("tracks", [])
        isrc_list: list[str] = md.get("isrc_list", [])
        artwork_w = int(md.get("artwork_width", 0) or 0)
        artwork_h = int(md.get("artwork_height", 0) or 0)

        def _f(label: str, value, fmt: str = "text"):
            if value is None or value == "" or value == 0:
                return None
            return {"label": label, "value": value, "format": fmt}

        track_lines: list[str] = []
        for i, t in enumerate(tracks_data, 1):
            parts = [f"Track {i}"]
            if t.get("title"):
                parts.append(t["title"])
            if t.get("isrc"):
                parts.append(t["isrc"])
            track_lines.append(" — ".join(parts))

        release_title = release.title or md.get("title", "")

        raw = [
            _f("Release Title",    release_title),
            _f("Artist",           release.artist),
            _f("Label",            md.get("label")),
            _f("Release Type",     md.get("release_type")),
            _f("Genre",            md.get("genre")),
            _f("Release Date",     str(release.release_date) if release.release_date else None),
            _f("UPC / Barcode",    release.upc),
            _f("P-Line",           md.get("p_line")),
            _f("C-Line",           md.get("c_line")),
            _f("Parental Warning", md.get("parental_warning")),
            _f("Territory",        md.get("territory")),
            _f("Publisher",        md.get("publisher")),
            _f("Track Count",      len(tracks_data) if tracks_data else None),
            _f("ISRCs",            ", ".join(isrc_list) if isrc_list else None),
            _f("Tracks",           track_lines, fmt="list") if track_lines else None,
            _f("Artwork",
               f"{artwork_w}×{artwork_h} px" if artwork_w and artwork_h else None),
        ]
        return [f for f in raw if f is not None]

    def _build_release_metadata(self, release: Release) -> ReleaseMetadata:
        """Construct a ReleaseMetadata from the Release model's stored metadata."""
        md = release.metadata_ or {}

        # ISRCs come from the tracks.isrc field — stored in metadata_ as a list
        isrc_list: list[str] = md.get("isrc_list", [])
        tracks_data: list[dict] = md.get("tracks", [])

        return ReleaseMetadata(
            title=release.title or "",
            artist=release.artist or "",
            upc=release.upc or "",
            label=md.get("label", ""),
            release_date=str(release.release_date) if release.release_date else "",
            release_type=md.get("release_type", ""),
            genre=md.get("genre", ""),
            language=md.get("language", ""),
            c_line=md.get("c_line", ""),
            p_line=md.get("p_line", ""),
            p_line_year=md.get("p_line_year", ""),
            publisher=md.get("publisher", ""),
            composers=md.get("composers", []),
            territory=md.get("territory", "Worldwide"),
            parental_warning=md.get("parental_warning", ""),
            artwork_width=md.get("artwork_width", 0),
            artwork_height=md.get("artwork_height", 0),
            artwork_format=md.get("artwork_format", ""),
            artwork_color_mode=md.get("artwork_color_mode", ""),
            sample_rate=md.get("sample_rate", 0),
            bit_depth=md.get("bit_depth", 0),
            loudness_lufs=md.get("loudness_lufs", 0.0),
            true_peak_dbtp=md.get("true_peak_dbtp", 0.0),
            tracks=tracks_data,
            isrc_list=isrc_list,
            apple_id=md.get("apple_id", ""),
            iswc=md.get("iswc", ""),
            preorder_date=md.get("preorder_date", ""),
            has_dolby_atmos=md.get("has_dolby_atmos", False),
            is_hi_res=md.get("is_hi_res", False),
        )

    async def _build_velocity_context(
        self, db: AsyncSession, release: Release
    ) -> VelocityContext:
        """Count recent releases by artist and org for fraud velocity checks."""
        from sqlalchemy import text

        thirty_days_ago = "NOW() - INTERVAL '30 days'"
        seven_days_ago = "NOW() - INTERVAL '7 days'"

        from sqlalchemy import text as sa_text
        artist_count_row = await db.execute(
            sa_text(
                "SELECT COUNT(*) FROM releases "
                "WHERE org_id = :org_id AND artist = :artist "
                "AND created_at >= NOW() - INTERVAL '30 days'"
            ),
            {"org_id": str(release.org_id), "artist": release.artist},
        )
        artist_count = artist_count_row.scalar() or 0

        org_count_row = await db.execute(
            sa_text(
                "SELECT COUNT(*) FROM releases "
                "WHERE org_id = :org_id "
                "AND created_at >= NOW() - INTERVAL '7 days'"
            ),
            {"org_id": str(release.org_id)},
        )
        org_count = org_count_row.scalar() or 0

        return VelocityContext(
            releases_by_artist_30d=int(artist_count),
            releases_by_org_7d=int(org_count),
        )

    async def _fetch_known_isrcs(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> dict[str, str]:
        """Return {isrc: release_id} for all tracks under this org."""
        rows = await db.execute(
            select(Track.isrc, Track.release_id)
            .join(Release, Release.id == Track.release_id)
            .where(
                Release.org_id == org_id,
                Track.isrc.isnot(None),
            )
        )
        return {row.isrc: str(row.release_id) for row in rows.all()}

    async def _ensure_rule(
        self, db: AsyncSession, rule_id: str, layer: str, severity: str
    ) -> None:
        """
        Upsert a minimal Rule row so ScanResult FK constraints are satisfied.

        Rules seeded from YAML files take precedence — this only creates
        a placeholder if the rule isn't already in the registry.
        """
        stmt = (
            pg_insert(Rule)
            .values(
                id=rule_id,
                layer=layer,
                severity=severity,
                title=rule_id.replace(".", " ").replace("_", " ").title(),
                category=layer,
                version="1.0.0",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.execute(stmt)

    async def _download_artifact(self, url: str) -> bytes:
        """Download a release artifact from S3, HTTP, or an inline data: URI."""
        from urllib.parse import urlparse
        parsed = urlparse(url)

        # Inline base64 data URI — used when S3 is not configured
        if parsed.scheme == "data":
            import base64
            # data:application/xml;base64,<payload>
            _header, _, payload = url.partition(",")
            if ";base64" in _header:
                return base64.b64decode(payload)
            return payload.encode()

        if parsed.scheme == "s3":
            import boto3
            from config import settings
            kwargs = {"region_name": settings.aws_region}
            if getattr(settings, "aws_access_key_id", None):
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            if getattr(settings, "s3_endpoint_url", None):
                kwargs["endpoint_url"] = settings.s3_endpoint_url
            s3 = boto3.client("s3", **kwargs)
            import io
            buf = io.BytesIO()
            s3.download_fileobj(parsed.netloc, parsed.path.lstrip("/"), buf)
            return buf.getvalue()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    def _fire_report_task(self, scan_id: str) -> None:
        """Fire the PDF report generation Celery task."""
        try:
            from tasks.generate_report import generate_report_task
            generate_report_task.delay(scan_id)
        except Exception as exc:
            logger.warning("Could not fire report task for scan %s: %s", scan_id, exc)

    async def _notify(
        self,
        org_row: "Organization | None",
        release: Release,
        scan: Scan,
        errors: list[str],
    ) -> None:
        """
        Send a scan-complete or scan-failed email notification.

        The recipient email is sourced from the org's settings dict
        (key: ``notification_email``).  If absent, falls back to the
        org's clerk_org_id-derived domain as a heuristic — and if that
        also isn't present the notification is silently skipped.
        """
        if not org_row:
            return

        recipient: str | None = (org_row.settings or {}).get("notification_email")
        if not recipient:
            return  # No email configured — skip silently

        from config import settings as app_settings
        from services.email_service import send_scan_complete, send_scan_failed

        dashboard_url = app_settings.frontend_url
        release_title = getattr(release, "title", "Untitled Release")
        org_name = getattr(org_row, "name", "Your organization")

        try:
            if scan.status == ScanStatus.complete:
                await send_scan_complete(
                    org_name=org_name,
                    recipient_email=recipient,
                    scan_id=str(scan.id),
                    release_title=release_title,
                    grade=scan.grade.value if scan.grade else "FAIL",
                    readiness_score=scan.readiness_score or 0,
                    total_issues=scan.total_issues or 0,
                    critical_count=scan.critical_count or 0,
                    warning_count=scan.warning_count or 0,
                    dashboard_url=dashboard_url,
                )
            elif scan.status == ScanStatus.failed:
                hint = errors[0] if errors else "An internal error occurred."
                await send_scan_failed(
                    org_name=org_name,
                    recipient_email=recipient,
                    scan_id=str(scan.id),
                    release_title=release_title,
                    error_hint=hint,
                    dashboard_url=dashboard_url,
                )
        except Exception as exc:
            logger.warning("Failed to send scan notification: %s", exc)
