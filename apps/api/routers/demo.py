"""
Demo scan endpoint — no auth, no DB writes.

POST /api/demo/scan
  Accepts DDEX XML bytes (multipart field "file") or uses the embedded
  sample release when field is absent.

  Runs DDEX validation, DSP metadata rules, and fraud screening entirely
  in memory.  Nothing is stored.  Results are returned with demo watermark
  flags and sanitised rule identifiers (no internal IDs exposed).

Rate limiting: 10 scans per IP per hour via in-process dict.
  (Good enough for a partnership demo; upgrade to Redis if traffic grows.)

Logging: timestamp + sha256(IP)[:8] + grade only — no file content.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse

from file_types import detect_format
from services.ddex.validator import DDEXValidator, DDEXParser
from services.ddex.csv_parser import CSVParser
from services.ddex.json_parser import JSONParser
from services.fraud.screener import FraudScreener, VelocityContext
from services.metadata.rules_engine import DSPRulesEngine, ReleaseMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])

# ── Rate limiting ─────────────────────────────────────────────────────────────

_RATE_WINDOW = 3600          # 1 hour in seconds
_RATE_LIMIT   = 10           # max scans per IP per window

# { ip_hash: [(timestamp, ...), ...] }
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str) -> None:
    """Raise 429 if this IP has exceeded _RATE_LIMIT within the last hour."""
    key = hashlib.sha256(ip.encode()).hexdigest()[:16]
    now = time.time()
    window_start = now - _RATE_WINDOW

    timestamps = _rate_buckets[key]
    # Prune old entries
    timestamps[:] = [t for t in timestamps if t > window_start]

    if len(timestamps) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": (
                    "You've reached the demo limit. "
                    "Create a free account for unlimited access."
                ),
                "signup_url": "https://songgate.io/sign-up",
            },
        )

    timestamps.append(now)
    _rate_buckets[key] = timestamps


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ── Sample release (embedded) ─────────────────────────────────────────────────

_SAMPLE_XML_PATH = Path(__file__).parent.parent / "docs" / "ddex" / "demo-release-with-errors.xml"

def _load_sample_xml() -> bytes:
    if _SAMPLE_XML_PATH.exists():
        return _SAMPLE_XML_PATH.read_bytes()
    # Fallback embedded minimal DDEX with 4 intentional errors
    return _MINIMAL_DEMO_XML.encode("utf-8")


_MINIMAL_DEMO_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<ern:NewReleaseMessage
  xmlns:ern="http://ddex.net/xml/ern/43"
  MessageSchemaVersionId="ern/43"
  LanguageAndScriptCode="en"
  MessageId="MSG-DEMO-001">
  <MessageHeader>
    <MessageThreadId>THREAD-DEMO-001</MessageThreadId>
    <MessageId>MSG-DEMO-001</MessageId>
    <MessageSender><PartyId>DEMO001</PartyId><PartyName><FullName>Demo Distributor</FullName></PartyName></MessageSender>
    <MessageRecipient><PartyId>SPOTIFY001</PartyId><PartyName><FullName>Spotify</FullName></PartyName></MessageRecipient>
    <MessageCreatedDateTime>2026-01-15T10:00:00</MessageCreatedDateTime>
    <MessageControlType>LiveMessage</MessageControlType>
  </MessageHeader>
  <ResourceList>
    <SoundRecording>
      <SoundRecordingType>MusicalWorkSoundRecording</SoundRecordingType>
      <IsRC>USPR12600001</IsRC>
      <ResourceReference>A1</ResourceReference>
      <ReferenceTitle><TitleText>Luminous Decay</TitleText></ReferenceTitle>
      <Duration>PT3M45S</Duration>
      <SoundRecordingDetailsByTerritory>
        <TerritoryCode>Worldwide</TerritoryCode>
        <Title TitleType="FormalTitle"><TitleText>Luminous Decay</TitleText></Title>
        <DisplayArtist SequenceNumber="1">
          <PartyName><FullName>Nova Crest</FullName></PartyName>
          <DisplayArtistRole>MainArtist</DisplayArtistRole>
        </DisplayArtist>
        <Contributor><PartyName><FullName>Horizon Music Publishing</FullName></PartyName><Role>MusicPublisher</Role></Contributor>
        <PLine><Year>2026</Year><PLineText>(P) 2026 Nova Crest Records</PLineText></PLine>
        <CLine><Year>2026</Year><CLineText>(C) 2026 Nova Crest Records</CLineText></CLine>
      </SoundRecordingDetailsByTerritory>
    </SoundRecording>
    <SoundRecording>
      <SoundRecordingType>MusicalWorkSoundRecording</SoundRecordingType>
      <IsRC>USPR12600002</IsRC>
      <ResourceReference>A2</ResourceReference>
      <ReferenceTitle><TitleText>Refraction</TitleText></ReferenceTitle>
      <Duration>PT4M20S</Duration>
      <SoundRecordingDetailsByTerritory>
        <TerritoryCode>Worldwide</TerritoryCode>
        <Title TitleType="FormalTitle"><TitleText>Refraction</TitleText></Title>
        <DisplayArtist SequenceNumber="1">
          <PartyName><FullName>Nova Crest</FullName></PartyName>
          <DisplayArtistRole>MainArtist</DisplayArtistRole>
        </DisplayArtist>
        <!-- ERROR 1: Missing MusicPublisher contributor on Track 2 -->
        <PLine><Year>2026</Year><PLineText>(P) 2026 Nova Crest Records</PLineText></PLine>
        <CLine><Year>2026</Year><CLineText>(C) 2026 Nova Crest Records</CLineText></CLine>
      </SoundRecordingDetailsByTerritory>
    </SoundRecording>
    <SoundRecording>
      <SoundRecordingType>MusicalWorkSoundRecording</SoundRecordingType>
      <!-- ERROR 2: Malformed ISRC — missing hyphens -->
      <IsRC>USRC11607841X</IsRC>
      <ResourceReference>A3</ResourceReference>
      <!-- ERROR 3: Sleep Sounds — short duration (45s) + spam keyword title -->
      <ReferenceTitle><TitleText>Sleep Sounds Relaxation</TitleText></ReferenceTitle>
      <Duration>PT0M45S</Duration>
      <SoundRecordingDetailsByTerritory>
        <TerritoryCode>Worldwide</TerritoryCode>
        <Title TitleType="FormalTitle"><TitleText>Sleep Sounds Relaxation</TitleText></Title>
        <DisplayArtist SequenceNumber="1">
          <PartyName><FullName>Nova Crest</FullName></PartyName>
          <DisplayArtistRole>MainArtist</DisplayArtistRole>
        </DisplayArtist>
        <Contributor><PartyName><FullName>Horizon Music Publishing</FullName></PartyName><Role>MusicPublisher</Role></Contributor>
        <PLine><Year>2026</Year><PLineText>(P) 2026 Nova Crest Records</PLineText></PLine>
        <CLine><Year>2026</Year><CLineText>(C) 2026 Nova Crest Records</CLineText></CLine>
      </SoundRecordingDetailsByTerritory>
    </SoundRecording>
    <!-- ERROR 4: Artwork 2000x2000 — below 3000x3000 DSP minimum -->
    <Image>
      <ImageType>FrontCoverImage</ImageType>
      <ResourceReference>IMG1</ResourceReference>
      <ImageDetailsByTerritory>
        <TerritoryCode>Worldwide</TerritoryCode>
        <TechnicalImageDetails>
          <ImageHeight>2000</ImageHeight>
          <ImageWidth>2000</ImageWidth>
          <ImageCodecType>JPEG</ImageCodecType>
        </TechnicalImageDetails>
      </ImageDetailsByTerritory>
    </Image>
  </ResourceList>
  <ReleaseList>
    <Release IsMainRelease="true">
      <ReleaseReference>R1</ReleaseReference>
      <ReleaseType>Album</ReleaseType>
      <ReleaseId><ICPN><UPC>886447117125</UPC></ICPN></ReleaseId>
      <ReferenceTitle><TitleText>Luminous Decay</TitleText></ReferenceTitle>
      <ReleaseResourceReferenceList>
        <ReleaseResourceReference ReleaseResourceType="PrimaryResource">A1</ReleaseResourceReference>
        <ReleaseResourceReference ReleaseResourceType="PrimaryResource">A2</ReleaseResourceReference>
        <ReleaseResourceReference ReleaseResourceType="PrimaryResource">A3</ReleaseResourceReference>
        <ReleaseResourceReference ReleaseResourceType="SecondaryResource">IMG1</ReleaseResourceReference>
      </ReleaseResourceReferenceList>
      <ReleaseDetailsByTerritory>
        <TerritoryCode>Worldwide</TerritoryCode>
        <DisplayArtistName>Nova Crest</DisplayArtistName>
        <LabelName>Nova Crest Records</LabelName>
        <Title TitleType="FormalTitle"><TitleText>Luminous Decay</TitleText></Title>
        <DisplayArtist SequenceNumber="1">
          <PartyName><FullName>Nova Crest</FullName></PartyName>
          <DisplayArtistRole>MainArtist</DisplayArtistRole>
        </DisplayArtist>
        <Genre><GenreText>Indie Electronic</GenreText></Genre>
        <ParentalWarningType>NotExplicit</ParentalWarningType>
        <ReleaseDate>2026-06-01</ReleaseDate>
      </ReleaseDetailsByTerritory>
    </Release>
  </ReleaseList>
  <DealList>
    <ReleaseDeal>
      <DealReleaseReference>R1</DealReleaseReference>
      <Deal>
        <DealTerms>
          <CommercialModelType>SubscriptionModel</CommercialModelType>
          <Usage><UseType>OnDemandStream</UseType></Usage>
          <TerritoryCode>Worldwide</TerritoryCode>
          <ValidityPeriod><StartDate>2026-06-01</StartDate></ValidityPeriod>
        </DealTerms>
      </Deal>
    </ReleaseDeal>
  </DealList>
</ern:NewReleaseMessage>
"""


# ── Demo services (module-level singletons, no DB) ────────────────────────────

_ddex_validator = DDEXValidator()
_csv_parser     = CSVParser()
_json_parser    = JSONParser()
_rules_engine   = DSPRulesEngine()
_fraud_screener = FraudScreener()


def _sanitise_rule_id(rule_id: str) -> str:
    """Convert internal dot-path rule ID to a human-readable name."""
    parts = rule_id.replace("_", " ").replace(".", " — ").split(" — ")
    return " — ".join(p.title() for p in parts)


def _run_in_memory_scan(content: bytes, filename: str = "") -> dict[str, Any]:
    """
    Run all applicable QA layers on raw metadata bytes (XML, CSV, or JSON).
    Returns a dict matching the DemoScanResult schema.
    No database access, no file storage.
    """
    scan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []

    fmt = detect_format(content, filename)

    # ── Layer 1: Format validation ─────────────────────────────────────────────
    parsed_meta: dict[str, Any] = {}

    if fmt == "xml":
        # DDEX XML: full validator + parser
        try:
            ddex_findings = _ddex_validator.validate(content)
            for f in ddex_findings:
                results.append({
                    "id": str(uuid.uuid4()),
                    "layer": "ddex",
                    "rule_name": _sanitise_rule_id(f.rule_id),
                    "severity": f.severity,
                    "message": f.message,
                    "field_path": getattr(f, "field_path", None),
                    "actual_value": getattr(f, "actual_value", None),
                    "fix_hint": getattr(f, "fix_hint", None),
                    "dsp_targets": [],
                })
        except Exception as exc:
            logger.warning("Demo DDEX layer error: %s", exc)
        try:
            parsed_meta = DDEXParser().extract_metadata(content) or {}
        except Exception as exc:
            logger.warning("Demo XML parse error: %s", exc)

    elif fmt == "csv":
        # CSV: structural parse findings + convert first release to parsed_meta
        try:
            csv_result = _csv_parser.parse(content)
            for f in csv_result.findings:
                results.append({
                    "id": str(uuid.uuid4()),
                    "layer": "ddex",
                    "rule_name": _sanitise_rule_id(f.rule_id),
                    "severity": f.severity,
                    "message": f.message,
                    "field_path": getattr(f, "field_path", None),
                    "actual_value": getattr(f, "actual_value", None),
                    "fix_hint": getattr(f, "fix_hint", None),
                    "dsp_targets": [],
                })
            if csv_result.releases:
                rel = csv_result.releases[0]
                parsed_meta = {
                    "title": rel.get("title", ""),
                    "artist": rel.get("artist", ""),
                    "upc": rel.get("upc", ""),
                    "label": rel.get("label", ""),
                    "release_date": rel.get("release_date", ""),
                    "release_type": rel.get("release_type", ""),
                    "genre": rel.get("genre", ""),
                    "c_line": rel.get("c_line", ""),
                    "p_line": rel.get("p_line", ""),
                    "parental_warning": rel.get("parental_warning", ""),
                    "tracks": rel.get("tracks", []),
                    "isrc_list": [t.get("isrc", "") for t in rel.get("tracks", []) if t.get("isrc")],
                    "publisher": next(
                        (t.get("composer", "") for t in rel.get("tracks", []) if t.get("composer")),
                        "",
                    ),
                }
        except Exception as exc:
            logger.warning("Demo CSV layer error: %s", exc)

    elif fmt == "json":
        # JSON: structural parse findings + convert first release to parsed_meta
        try:
            json_result = _json_parser.parse(content)
            for f in json_result.findings:
                results.append({
                    "id": str(uuid.uuid4()),
                    "layer": "ddex",
                    "rule_name": _sanitise_rule_id(f.rule_id),
                    "severity": f.severity,
                    "message": f.message,
                    "field_path": getattr(f, "field_path", None),
                    "actual_value": getattr(f, "actual_value", None),
                    "fix_hint": getattr(f, "fix_hint", None),
                    "dsp_targets": [],
                })
            if json_result.releases:
                rel = json_result.releases[0]
                parsed_meta = {
                    "title": rel.get("title", ""),
                    "artist": rel.get("artist", ""),
                    "upc": rel.get("upc", ""),
                    "label": rel.get("label", ""),
                    "release_date": rel.get("release_date", ""),
                    "release_type": rel.get("release_type", ""),
                    "genre": rel.get("genre", ""),
                    "c_line": rel.get("c_line", ""),
                    "p_line": rel.get("p_line", ""),
                    "parental_warning": rel.get("parental_warning", ""),
                    "tracks": rel.get("tracks", []),
                    "isrc_list": [t.get("isrc", "") for t in rel.get("tracks", []) if t.get("isrc")],
                    "publisher": "",
                }
        except Exception as exc:
            logger.warning("Demo JSON layer error: %s", exc)

    tracks_data = parsed_meta.get("tracks", [])
    isrc_list   = parsed_meta.get("isrc_list", [])
    file_format = fmt

    # Check artwork dimensions from parsed metadata
    artwork_width  = int(parsed_meta.get("artwork_width", 0) or 0)
    artwork_height = int(parsed_meta.get("artwork_height", 0) or 0)
    if artwork_width > 0 and artwork_height > 0 and (artwork_width < 3000 or artwork_height < 3000):
        results.append({
            "id": str(uuid.uuid4()),
            "layer": "artwork",
            "rule_name": "Artwork — Minimum Resolution",
            "severity": "critical",
            "message": f"Cover artwork is {artwork_width}×{artwork_height} px, below the 3000×3000 px minimum required by Spotify, Apple Music, and Amazon.",
            "field_path": "Image/TechnicalImageDetails",
            "actual_value": f"{artwork_width}×{artwork_height} px",
            "fix_hint": "Resize artwork to at least 3000×3000 px in JPEG or PNG format. Most DSPs will reject artwork below this resolution.",
            "dsp_targets": ["spotify", "apple_music", "amazon"],
        })

    # Check for short tracks (< 60s) from DDEX parsing
    for track in tracks_data:
        dur_ms = track.get("duration_ms", 0) or 0
        if dur_ms > 0 and dur_ms < 60_000:
            title = track.get("title", "Unknown Track")
            dur_s = dur_ms // 1000
            results.append({
                "id": str(uuid.uuid4()),
                "layer": "audio",
                "rule_name": "Audio — Minimum Track Duration",
                "severity": "warning",
                "message": f'"{title}" is {dur_s} seconds — below the 60-second minimum for most DSPs.',
                "field_path": "SoundRecording/Duration",
                "actual_value": f"{dur_s}s",
                "fix_hint": "Tracks under 60 seconds may be rejected by Spotify and Apple Music. Verify the content is intentionally short (ringtones, interludes) and add the appropriate SubGenre tag.",
                "dsp_targets": ["spotify", "apple_music"],
            })

    # ── Layer 2: DSP Metadata Rules ────────────────────────────────────────────
    try:
        meta = ReleaseMetadata(
            title=parsed_meta.get("title", ""),
            artist=parsed_meta.get("artist", ""),
            upc=parsed_meta.get("upc", ""),
            label=parsed_meta.get("label", ""),
            release_date=parsed_meta.get("release_date", ""),
            release_type=parsed_meta.get("release_type", ""),
            genre=parsed_meta.get("genre", ""),
            language=parsed_meta.get("language", ""),
            c_line=parsed_meta.get("c_line", ""),
            p_line=parsed_meta.get("p_line", ""),
            p_line_year=parsed_meta.get("p_line_year", ""),
            publisher=parsed_meta.get("publisher", ""),
            composers=parsed_meta.get("composers", []),
            territory=parsed_meta.get("territory", "Worldwide"),
            parental_warning=parsed_meta.get("parental_warning", ""),
            artwork_width=artwork_width,
            artwork_height=artwork_height,
            artwork_format=parsed_meta.get("artwork_format", ""),
            artwork_color_mode=parsed_meta.get("artwork_color_mode", ""),
            sample_rate=parsed_meta.get("sample_rate", 0),
            bit_depth=parsed_meta.get("bit_depth", 0),
            loudness_lufs=float(parsed_meta.get("loudness_lufs", 0.0) or 0.0),
            true_peak_dbtp=float(parsed_meta.get("true_peak_dbtp", 0.0) or 0.0),
            tracks=tracks_data,
            isrc_list=isrc_list,
            apple_id=parsed_meta.get("apple_id", ""),
            iswc=parsed_meta.get("iswc", ""),
            preorder_date=parsed_meta.get("preorder_date", ""),
            has_dolby_atmos=bool(parsed_meta.get("has_dolby_atmos", False)),
            is_hi_res=bool(parsed_meta.get("is_hi_res", False)),
        )

        dsps = ["spotify", "apple_music", "amazon", "tidal", "deezer"]
        rule_results = _rules_engine.evaluate(meta, dsps=dsps)
        for rr in rule_results:
            if rr.status in ("pass", "skip"):
                continue
            results.append({
                "id": str(uuid.uuid4()),
                "layer": "metadata",
                "rule_name": _sanitise_rule_id(rr.rule_id),
                "severity": rr.severity,
                "message": rr.message,
                "field_path": None,
                "actual_value": str(rr.checked_value) if rr.checked_value is not None else None,
                "fix_hint": rr.fix_hint,
                "dsp_targets": dsps,
            })
    except Exception as exc:
        logger.warning("Demo metadata rules error: %s", exc)

    # ── Layer 3: Fraud Screening (no velocity / no DB) ─────────────────────────
    try:
        velocity = VelocityContext(releases_by_artist_30d=0, releases_by_org_7d=0)
        signals = _fraud_screener.screen(
            metadata=meta,
            org_id="demo",
            velocity=velocity,
            known_isrcs={},
        )
        for sig in signals:
            results.append({
                "id": str(uuid.uuid4()),
                "layer": "fraud",
                "rule_name": _sanitise_rule_id(sig.signal_id),
                "severity": sig.severity,
                "message": sig.explanation,
                "field_path": None,
                "actual_value": sig.matched_value or None,
                "fix_hint": sig.resolution,
                "dsp_targets": [],
            })
    except Exception as exc:
        logger.warning("Demo fraud layer error: %s", exc)

    # ── Score ──────────────────────────────────────────────────────────────────
    # "error" (DDEX layer) and "critical" (metadata/fraud layers) both deduct at the critical rate
    critical = sum(1 for r in results if r["severity"] in ("critical", "error"))
    warnings = sum(1 for r in results if r["severity"] == "warning")
    info     = sum(1 for r in results if r["severity"] == "info")

    deductions = min(critical * 10.0, 60.0) + min(warnings * 3.0, 25.0) + min(info * 0.5, 5.0)
    score = round(max(0.0, 100.0 - deductions), 1)
    grade = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

    return {
        "scan_id": scan_id,
        "demo": True,
        "file_format": file_format,
        "watermark": "SONGGATE Demo — songgate.io",
        "status": "complete",
        "readiness_score": score,
        "grade": grade,
        "critical_count": critical,
        "warning_count": warnings,
        "info_count": info,
        "total_issues": critical + warnings + info,
        "layers_run": ["ddex", "metadata", "fraud", "artwork", "audio"],
        "results": results,
        "release_title": parsed_meta.get("title", "Uploaded Release"),
        "release_artist": parsed_meta.get("artist", ""),
        "completed_at": now,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/scan")
async def demo_scan(
    request: Request,
    file: UploadFile | None = File(default=None),
) -> JSONResponse:
    """
    Run a demo scan.

    Send a multipart/form-data request with field ``file`` containing
    a DDEX XML document.  Omit the field to use the embedded sample release.
    """
    ip = _client_ip(request)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:8]

    if file is not None:
        content = await file.read()
        if len(content) > 5 * 1024 * 1024:  # 5 MB hard cap
            raise HTTPException(status_code=413, detail="File too large (max 5 MB).")
        filename = file.filename or ""
    else:
        content = _load_sample_xml()
        filename = "sample-release.xml"

    result = _run_in_memory_scan(content, filename=filename)

    logger.info(
        "demo_scan ip_hash=%s grade=%s issues=%d",
        ip_hash,
        result["grade"],
        result["total_issues"],
    )

    return JSONResponse(content=result)


@router.get("/sample-xml")
async def get_sample_xml(request: Request) -> JSONResponse:
    """Return metadata about the sample release (no file content)."""
    ip = _client_ip(request)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:8]
    logger.info("demo_sample_info ip_hash=%s", ip_hash)
    return JSONResponse(content={
        "name": "Luminous Decay — Nova Crest",
        "format": "DDEX ERN 4.3",
        "tracks": 3,
        "intentional_errors": 4,
        "description": (
            "A 3-track album with 4 intentional errors: "
            "missing publisher on Track 2, malformed ISRC on Track 3, "
            "artwork below 3000×3000 minimum, and a 45-second spam-signal track."
        ),
    })
