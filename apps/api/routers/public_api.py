"""
Public REST API — /api/v1/

Authenticated via API keys (ropqa_sk_…).  Every endpoint is fully documented
for OpenAPI / Swagger UI at /docs.

Routes
------
Keys
  POST   /api/v1/keys
  GET    /api/v1/keys
  DELETE /api/v1/keys/{key_id}

Releases
  POST   /api/v1/releases
  GET    /api/v1/releases
  GET    /api/v1/releases/{release_id}
  DELETE /api/v1/releases/{release_id}

Scans
  POST   /api/v1/releases/{release_id}/scan
  GET    /api/v1/scans/{scan_id}
  GET    /api/v1/scans/{scan_id}/results
  GET    /api/v1/scans/{scan_id}/report
  PATCH  /api/v1/scans/{scan_id}/results/{result_id}

Batch
  POST   /api/v1/batch/scan
  GET    /api/v1/batch/{job_id}

Analytics
  GET    /api/v1/analytics/top-issues
  GET    /api/v1/analytics/pass-rate
  GET    /api/v1/analytics/dsp-breakdown
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.api_key import APIKey
from models.batch_job import BatchJob, BatchJobStatus
from models.organization import Organization
from models.release import Release, ReleaseStatus, SubmissionFormat
from models.scan import Scan, ScanGrade, ScanStatus
from models.scan_result import ScanResult
from services.scan_orchestrator import ScanOrchestrator

router = APIRouter(prefix="/api/v1", tags=["Public API v1"])

# ─────────────────────────────────────────────────────────────────────────────
# API key helpers
# ─────────────────────────────────────────────────────────────────────────────

_KEY_PREFIX_LEN = 8    # visible prefix stored in DB — ropqa_sk_ (9) + 8 = 17 chars, fits VARCHAR(20)
_KEY_TOTAL_LEN  = 40   # random hex suffix length (total entropy: 160 bits)
_KEY_SCHEME     = "ropqa_sk_"


def _generate_key() -> str:
    """Return a fresh plaintext key: ropqa_sk_<40 hex chars>."""
    return _KEY_SCHEME + secrets.token_hex(_KEY_TOTAL_LEN // 2)


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _key_prefix(plaintext: str) -> str:
    """First 16 chars of the random part — safe to display."""
    suffix = plaintext[len(_KEY_SCHEME):]
    return _KEY_SCHEME + suffix[:_KEY_PREFIX_LEN]


# ─────────────────────────────────────────────────────────────────────────────
# Auth dependency
# ─────────────────────────────────────────────────────────────────────────────

async def _get_api_key_org(
    request: Request,
    authorization: Annotated[
        str,
        Header(
            description=(
                "API key in the form `Bearer ropqa_sk_…`. "
                "Obtain a key from `POST /api/v1/keys`."
            )
        ),
    ],
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Resolve the Organization that owns the presented API key.

    Raises **401** if the key is missing, malformed, unknown, or revoked.
    Updates `last_used_at` on every successful auth.
    """
    scheme, _, raw_key = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw_key:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer ropqa_sk_…'",
        )
    if not raw_key.startswith(_KEY_SCHEME):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format — expected ropqa_sk_… key",
        )

    key_hash = _hash_key(raw_key)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()

    if api_key is None or api_key.revoked:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    # Touch last_used_at without blocking on the response
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    # Fetch org
    org_result = await db.execute(
        select(Organization).where(Organization.id == api_key.org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Organization not found")

    # Expose org context to middleware (rate limiter + usage recorder)
    request.state.org_id     = str(org.id)
    request.state.org_tier   = org.tier
    request.state.api_key_id = str(api_key.id)

    return org


OrgDep = Annotated[Organization, Depends(_get_api_key_org)]


# ─────────────────────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human-readable label for this key.",
        examples=["CI pipeline", "Distributor webhook"],
    )
    org_id: str | None = Field(
        None,
        description=(
            "Organization UUID. Required only when using the admin bootstrap token "
            "(`Authorization: Bearer <admin_token>`). Ignored for normal API-key auth."
        ),
    )


class APIKeyCreated(BaseModel):
    """Returned **once** on key creation.  `key` is never shown again."""
    id: uuid.UUID
    name: str
    key: str = Field(description="Full plaintext key — store it securely now.")
    key_prefix: str
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyRead(BaseModel):
    """Safe summary — never exposes the key hash or plaintext."""
    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked: bool
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicReleaseIn(BaseModel):
    title: str = Field(..., examples=["Midnight Sessions"])
    artist: str = Field(..., examples=["Luna Park"])
    submission_format: SubmissionFormat = Field(default=SubmissionFormat.JSON)
    upc: str | None = Field(None, examples=["00602507474195"])
    release_date: date | None = Field(None, examples=["2026-06-01"])
    external_id: str | None = Field(
        None,
        description="Your internal release ID — stored as-is for correlation.",
        examples=["REL-20260601-LP"],
    )
    trigger_scan: bool = Field(
        True,
        description="Immediately queue a QA scan after creating the release.",
    )


class PublicReleaseOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    external_id: str | None
    title: str
    artist: str
    upc: str | None
    release_date: date | None
    submission_format: SubmissionFormat
    status: ReleaseStatus
    archived_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicReleaseWithScan(BaseModel):
    release: PublicReleaseOut
    scan: "PublicScanOut | None" = None


class PublicScanOut(BaseModel):
    id: uuid.UUID
    release_id: uuid.UUID
    status: ScanStatus
    readiness_score: float | None
    grade: ScanGrade | None
    total_issues: int
    critical_count: int
    warning_count: int
    info_count: int
    layers_run: list[str]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicScanResultOut(BaseModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    layer: str
    rule_id: str
    severity: str
    status: str
    message: str
    field_path: str | None
    actual_value: str | None
    expected_value: str | None
    fix_hint: str | None
    dsp_targets: list[str]
    resolved: bool
    resolution: str | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolveResultIn(BaseModel):
    resolution: str = Field(
        ...,
        description="Brief explanation of how the issue was addressed.",
        examples=["Updated ISRC in source metadata"],
    )
    resolved_by: str = Field(
        ...,
        description="Identifier of the user or system resolving this finding.",
        examples=["user_2abc123", "ci-bot"],
    )


class ReportURLOut(BaseModel):
    scan_id: str
    report_url: str = Field(description="Presigned S3 GET URL, valid for 1 hour.")
    report_generated_at: datetime | None
    filename: str


class PaginatedReleasesOut(BaseModel):
    items: list[PublicReleaseOut]
    total: int
    page: int
    limit: int


class ScanResultsOut(BaseModel):
    scan: PublicScanOut
    results: list[PublicScanResultOut]
    total: int


# ── Batch ────────────────────────────────────────────────────────────────────

class BatchReleaseIn(BaseModel):
    title: str = Field(..., examples=["Midnight Sessions"])
    artist: str = Field(..., examples=["Luna Park"])
    submission_format: SubmissionFormat = Field(default=SubmissionFormat.JSON)
    upc: str | None = None
    external_id: str | None = None


class BatchScanIn(BaseModel):
    releases: list[BatchReleaseIn] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Array of releases to create and scan in one batch (max 100).",
    )
    label: str | None = Field(
        None,
        max_length=200,
        description="Optional label to identify this batch in the status endpoint.",
        examples=["Q2-2026 catalog push"],
    )


class BatchJobOut(BaseModel):
    job_id: uuid.UUID
    status: BatchJobStatus
    label: str | None
    total: int
    completed: int
    failed: int
    release_ids: list[str]
    scan_ids: list[str]
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ── Analytics ────────────────────────────────────────────────────────────────

class TopIssueEntry(BaseModel):
    rule_id: str
    layer: str
    severity: str
    occurrences: int


class TopIssuesOut(BaseModel):
    period: str = Field(description="ISO-8601 month: YYYY-MM")
    items: list[TopIssueEntry]


class PassRatePoint(BaseModel):
    date: str = Field(description="ISO-8601 date: YYYY-MM-DD")
    total_scans: int
    passed: int
    pass_rate: float


class PassRateOut(BaseModel):
    period_days: int
    series: list[PassRatePoint]


class DSPBreakdownEntry(BaseModel):
    dsp: str
    critical_unresolved: int
    warning_unresolved: int
    total_issues: int


class DSPBreakdownOut(BaseModel):
    items: list[DSPBreakdownEntry]


# ── Analytics overview (single-call dashboard payload) ───────────────────────

class AggregateStats(BaseModel):
    total_releases_scanned: int
    total_issues_found: int
    issues_resolved: int
    false_positive_rate: float = Field(
        description="Percentage of findings that were resolved without code changes (proxy for false positives)."
    )


class TopIssueItem(BaseModel):
    rule_id: str
    rule_label: str = Field(description="Human-readable rule name derived from rule_id.")
    layer: str
    severity: str
    occurrences: int


class DSPMatrixRow(BaseModel):
    dsp: str
    avg_pass_rate: float
    trend: float = Field(
        description="Change in pass rate vs previous calendar month (percentage points, positive = improving)."
    )
    total_scans: int
    top_failures: list[str] = Field(description="Top 3 failing rule_ids for this DSP.")


class FraudSignalItem(BaseModel):
    signal: str = Field(description="Short signal name derived from the rule_id.")
    rule_id: str
    total_flags: int
    confirmed: int = Field(description="Flags marked resolved (operator-confirmed).")


class FraudSummary(BaseModel):
    total_flags_this_month: int
    confirmed: int
    dismissed: int
    confirmation_rate: float
    by_type: list[FraudSignalItem]


class VelocityPoint(BaseModel):
    week: str = Field(description="ISO-8601 week start date (Monday).")
    scans: int


class AnalyticsOverview(BaseModel):
    aggregate: AggregateStats
    top_issues: list[TopIssueItem]
    dsp_matrix: list[DSPMatrixRow]
    fraud_signals: FraudSummary
    velocity: list[VelocityPoint]
    cached_at: datetime
    cache_ttl_seconds: int = 3600


class ShareTokenOut(BaseModel):
    token: str
    expires_at: datetime = Field(description="UTC expiry — share links are valid for 7 days.")


# ─────────────────────────────────────────────────────────────────────────────
# ── Keys ──────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/keys",
    response_model=APIKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    description=(
        "Generate a new API key scoped to the authenticated organization. "
        "The full key value is returned **once** — store it immediately, as it "
        "cannot be retrieved again. Keys take effect instantly."
    ),
    responses={
        201: {
            "description": "Key created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "018f2b3c-0000-7000-8000-000000000001",
                        "name": "CI pipeline",
                        "key": "ropqa_sk_a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6",
                        "key_prefix": "ropqa_sk_a1b2c3d4e5f6a1b2",
                        "created_at": "2026-04-14T12:00:00Z",
                    }
                }
            },
        }
    },
)
async def create_api_key(
    payload: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None),
) -> APIKeyCreated:
    from config import settings

    # ── Resolve org: normal API-key auth OR dev admin bootstrap ───────────────
    org: Organization | None = None

    if authorization:
        scheme, _, raw_key = authorization.partition(" ")
        if scheme.lower() == "bearer":
            # Admin bootstrap path (dev only)
            if (
                settings.admin_token
                and settings.environment in ("development", "test")
                and raw_key == settings.admin_token
            ):
                if not payload.org_id:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        detail="org_id is required when using the admin bootstrap token.",
                    )
                try:
                    org_uuid = uuid.UUID(payload.org_id)
                except ValueError:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid org_id")
                result = await db.execute(select(Organization).where(Organization.id == org_uuid))
                org = result.scalar_one_or_none()
                if org is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
            # Normal API-key auth path
            elif raw_key.startswith(_KEY_SCHEME):
                key_hash = _hash_key(raw_key)
                result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
                api_key_row = result.scalar_one_or_none()
                if api_key_row is None or api_key_row.revoked:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
                api_key_row.last_used_at = datetime.now(timezone.utc)
                await db.commit()
                org_result = await db.execute(select(Organization).where(Organization.id == api_key_row.org_id))
                org = org_result.scalar_one_or_none()

    if org is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Provide a valid 'Authorization: Bearer ropqa_sk_…' header, "
                "or use the admin bootstrap token with org_id in the request body."
            ),
        )

    plaintext = _generate_key()
    api_key = APIKey(
        id=uuid.uuid4(),
        org_id=org.id,
        name=payload.name,
        key_prefix=_key_prefix(plaintext),
        key_hash=_hash_key(plaintext),
        created_at=datetime.now(timezone.utc),
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return APIKeyCreated(
        id=api_key.id,
        name=api_key.name,
        key=plaintext,
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
    )


@router.get(
    "/keys",
    response_model=list[APIKeyRead],
    summary="List API keys",
    description=(
        "Return all active (non-revoked) API keys for the organization. "
        "Plaintext key values are never returned — only the prefix and metadata."
    ),
)
async def list_api_keys(
    org: OrgDep,
    include_revoked: bool = Query(False, description="Include revoked keys in the response."),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyRead]:
    q = select(APIKey).where(APIKey.org_id == org.id)
    if not include_revoked:
        q = q.where(APIKey.revoked.is_(False))
    q = q.order_by(APIKey.created_at.desc())
    rows = await db.execute(q)
    return [APIKeyRead.model_validate(k) for k in rows.scalars().all()]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke API key",
    description=(
        "Revoke an API key by ID.  Revoked keys are rejected immediately on "
        "the next request. This action cannot be undone."
    ),
)
async def revoke_api_key(
    key_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.org_id == org.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="API key not found")
    if api_key.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Key is already revoked")
    api_key.revoked = True
    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ── Releases ──────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/releases",
    response_model=PublicReleaseWithScan,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create release and trigger scan",
    description=(
        "Create a new release record and optionally queue an automated QA scan. "
        "When `trigger_scan` is `true` (default), the scan runs asynchronously and "
        "the response includes a `scan` object with `status: queued`. "
        "Poll `GET /api/v1/scans/{scan_id}` for results."
    ),
    responses={
        202: {
            "description": "Release created; scan queued",
            "content": {
                "application/json": {
                    "example": {
                        "release": {
                            "id": "018f2b3c-0000-7000-8000-000000000010",
                            "title": "Midnight Sessions",
                            "artist": "Luna Park",
                            "status": "pending",
                        },
                        "scan": {
                            "id": "018f2b3c-0000-7000-8000-000000000020",
                            "status": "queued",
                            "readiness_score": None,
                        },
                    }
                }
            },
        }
    },
)
async def create_release(
    payload: PublicReleaseIn,
    background_tasks: BackgroundTasks,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> PublicReleaseWithScan:
    release = Release(
        id=uuid.uuid4(),
        org_id=org.id,
        external_id=payload.external_id,
        title=payload.title,
        artist=payload.artist,
        upc=payload.upc,
        release_date=payload.release_date,
        submission_format=payload.submission_format,
        status=ReleaseStatus.pending,
        created_at=datetime.now(timezone.utc),
    )
    db.add(release)
    await db.flush()

    scan_out: Scan | None = None
    if payload.trigger_scan:
        scan_out = Scan(
            id=uuid.uuid4(),
            release_id=release.id,
            org_id=org.id,
            status=ScanStatus.queued,
            layers_run=[],
            created_at=datetime.now(timezone.utc),
        )
        db.add(scan_out)

    await db.commit()
    await db.refresh(release)
    if scan_out:
        await db.refresh(scan_out)
        scan_id = str(scan_out.id)
        release_id = str(release.id)
        org_id = str(org.id)
        background_tasks.add_task(
            _run_scan_bg,
            release_id=release_id,
            scan_id=scan_id,
            org_id=org_id,
        )

    return PublicReleaseWithScan(
        release=PublicReleaseOut.model_validate(release),
        scan=PublicScanOut.model_validate(scan_out) if scan_out else None,
    )


@router.post(
    "/releases/upload-ddex",
    response_model=PublicReleaseWithScan,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload DDEX XML and create release",
    description=(
        "Accept a DDEX ERN XML file (`multipart/form-data`). "
        "The file is uploaded to S3, parsed to extract title/artist/ISRC metadata, "
        "and a release record is created. If `trigger_scan` is true (default) a QA "
        "scan starts immediately and the response includes a `scan` object with "
        "`status: queued`. Poll `GET /api/v1/scans/{scan_id}` for results."
    ),
)
async def upload_ddex(
    background_tasks: BackgroundTasks,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="DDEX ERN XML file"),
    trigger_scan: bool = Form(True, description="Immediately queue a QA scan"),
    external_id: str | None = Form(None, description="Your internal release ID"),
) -> PublicReleaseWithScan:
    import boto3, re as _re
    from botocore.config import Config as BotoConfig
    from config import settings
    from services.ddex.validator import DDEXParser

    content = await file.read()

    # ── Parse DDEX to extract title / artist ───────────────────────────────
    title = "Unknown Release"
    artist = "Unknown Artist"
    parsed: dict = {}
    try:
        parsed = DDEXParser().extract_metadata(content)
        if parsed.get("title"):
            title = parsed["title"]
        if parsed.get("artist"):
            artist = parsed["artist"]
    except Exception:
        pass  # fall back to defaults; validator will catch any structural issues

    # ── Upload XML to S3 (or fall back to inline data URI when S3 is unconfigured) ──
    import base64 as _b64

    if settings.aws_access_key_id or settings.s3_endpoint_url:
        safe_name = _re.sub(r"[^\w.\-]", "_", file.filename or "release.xml")
        s3_key = f"ropqa/{org.id}/releases/ddex-uploads/{uuid.uuid4()}/{safe_name}"

        s3_kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id:
            s3_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            s3_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.s3_endpoint_url:
            s3_kwargs["endpoint_url"] = settings.s3_endpoint_url

        s3 = boto3.client("s3", **s3_kwargs)
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=content,
            ContentType="application/xml",
        )
        raw_package_url = (
            f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{s3_key}"
            if settings.s3_endpoint_url
            else f"s3://{settings.s3_bucket}/{s3_key}"
        )
    else:
        # No S3 configured — store content inline as a data URI.
        # The scan orchestrator's _download_artifact handles the data: scheme.
        encoded = _b64.b64encode(content).decode()
        raw_package_url = f"data:application/xml;base64,{encoded}"

    # ── Detect DDEX version from namespace ────────────────────────────────
    detected_format = SubmissionFormat.DDEX_ERN_43  # default
    try:
        from lxml import etree as _etree
        _root = _etree.fromstring(content)
        _ns = _root.tag[1:].split("}")[0] if _root.tag.startswith("{") else ""
        if "ern/42" in _ns:
            detected_format = SubmissionFormat.DDEX_ERN_42
    except Exception:
        pass

    # ── Create release row ─────────────────────────────────────────────────
    release = Release(
        id=uuid.uuid4(),
        org_id=org.id,
        external_id=external_id,
        title=title,
        artist=artist,
        submission_format=detected_format,
        raw_package_url=raw_package_url,
        status=ReleaseStatus.ingesting,
        created_at=datetime.now(timezone.utc),
    )
    db.add(release)
    await db.flush()

    # Create Track rows from parsed DDEX so per-track endpoints work immediately
    from models.track import Track as TrackModel
    for idx, t in enumerate(parsed.get("tracks", []) if isinstance(parsed, dict) else [], start=1):
        raw_isrc = t.get("isrc") or None
        # Normalize ISRC: strip hyphens so "US-PR1-26-00001" → "USPR1260001" (12 chars max)
        isrc = raw_isrc.replace("-", "")[:12] if raw_isrc else None
        db.add(TrackModel(
            id=uuid.uuid4(),
            release_id=release.id,
            isrc=isrc,
            title=t.get("title") or "Unknown",
            track_number=idx,
            duration_ms=t.get("duration_ms"),
        ))

    scan_out: Scan | None = None
    if trigger_scan:
        scan_out = Scan(
            id=uuid.uuid4(),
            release_id=release.id,
            org_id=org.id,
            status=ScanStatus.queued,
            layers_run=[],
            created_at=datetime.now(timezone.utc),
        )
        db.add(scan_out)

    await db.commit()
    await db.refresh(release)
    if scan_out:
        await db.refresh(scan_out)
        background_tasks.add_task(
            _run_scan_bg,
            release_id=str(release.id),
            scan_id=str(scan_out.id),
            org_id=str(org.id),
        )

    return PublicReleaseWithScan(
        release=PublicReleaseOut.model_validate(release),
        scan=PublicScanOut.model_validate(scan_out) if scan_out else None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /releases/{release_id}/artwork   — upload cover art
# ──────────────────────────────────────────────────────────────────────────────

class ArtworkUploadOut(BaseModel):
    release_id: str
    artwork_width: int
    artwork_height: int
    message: str


@router.post(
    "/releases/{release_id}/artwork",
    response_model=ArtworkUploadOut,
    summary="Upload cover artwork",
    description=(
        "Upload a JPEG or PNG cover image for the release. The image is stored inline "
        "and will be validated against all DSP artwork requirements during the next scan. "
        "Minimum 3000×3000 px required by all major DSPs."
    ),
)
async def upload_artwork(
    release_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="JPEG or PNG cover image"),
) -> ArtworkUploadOut:
    import base64 as _b64
    from PIL import Image as _Image
    import io as _io

    release = await _get_release_for_org(db, release_id, org.id)

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Artwork must be under 15 MB.")

    # Validate it's a real image and get dimensions
    try:
        img = _Image.open(_io.BytesIO(content))
        img.verify()
        img = _Image.open(_io.BytesIO(content))  # re-open after verify
        width, height = img.size
        fmt = img.format or "JPEG"
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid image file: {exc}")

    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    encoded = _b64.b64encode(content).decode()
    data_uri = f"data:{mime};base64,{encoded}"

    existing = dict(release.metadata_ or {})
    existing["artwork_url"] = data_uri
    existing["artwork_width"] = width
    existing["artwork_height"] = height
    release.metadata_ = existing
    await db.commit()

    return ArtworkUploadOut(
        release_id=str(release_id),
        artwork_width=width,
        artwork_height=height,
        message=f"Artwork uploaded ({width}×{height} px). Run a scan to validate DSP requirements.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET  /releases/{release_id}/tracks                       — list tracks
# POST /releases/{release_id}/tracks/{track_id}/audio-url  — set audio URL
# ──────────────────────────────────────────────────────────────────────────────

class TrackOut(BaseModel):
    id: str
    title: str
    isrc: str | None
    track_number: int | None
    duration_ms: int | None
    audio_url: str | None


@router.get(
    "/releases/{release_id}/tracks",
    response_model=list[TrackOut],
    summary="List tracks",
    description="Return all tracks for a release with their IDs (needed to set audio URLs).",
)
async def list_tracks(
    release_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> list[TrackOut]:
    from models.track import Track as TrackModel

    await _get_release_for_org(db, release_id, org.id)

    result = await db.execute(
        select(TrackModel)
        .where(TrackModel.release_id == release_id)
        .order_by(TrackModel.track_number)
    )
    tracks = list(result.scalars().all())
    return [
        TrackOut(
            id=str(t.id),
            title=t.title,
            isrc=t.isrc,
            track_number=t.track_number,
            duration_ms=t.duration_ms,
            audio_url=t.audio_url,
        )
        for t in tracks
    ]


class AudioUrlIn(BaseModel):
    audio_url: str = Field(..., description="Publicly accessible URL to the audio file (FLAC, WAV, MP3).")


class AudioUrlOut(BaseModel):
    track_id: str
    audio_url: str
    message: str


@router.post(
    "/releases/{release_id}/tracks/{track_id}/audio-url",
    response_model=AudioUrlOut,
    summary="Set track audio URL",
    description=(
        "Provide a publicly accessible URL to an audio file for a track. "
        "The URL will be used during the next scan to validate loudness (LUFS), "
        "duration, codec, and sample-rate requirements per DSP."
    ),
)
async def set_track_audio_url(
    release_id: uuid.UUID,
    track_id: uuid.UUID,
    body: AudioUrlIn,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> AudioUrlOut:
    from models.track import Track

    # Verify release ownership
    await _get_release_for_org(db, release_id, org.id)

    track_result = await db.execute(
        select(Track).where(Track.id == track_id, Track.release_id == release_id)
    )
    track = track_result.scalar_one_or_none()
    if not track:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Track not found for this release.")

    track.audio_url = body.audio_url
    await db.commit()

    return AudioUrlOut(
        track_id=str(track_id),
        audio_url=body.audio_url,
        message="Audio URL set. Run a scan to validate loudness and format requirements.",
    )


@router.get(
    "/releases",
    response_model=PaginatedReleasesOut,
    summary="List releases",
    description=(
        "Return a paginated list of releases for the organization. "
        "Supports filtering by status and searching by title/artist. "
        "Archived releases are excluded by default."
    ),
)
async def list_releases(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="1-based page number."),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)."),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by release status: pending, ready, complete, failed.",
    ),
    search: str | None = Query(
        None,
        max_length=200,
        description="Case-insensitive substring match on title or artist.",
    ),
    include_archived: bool = Query(
        False, description="Include archived releases."
    ),
) -> PaginatedReleasesOut:
    q = select(Release).where(Release.org_id == org.id)

    if not include_archived:
        q = q.where(Release.archived_at.is_(None))
    if status_filter:
        q = q.where(Release.status == status_filter)
    if search:
        pattern = f"%{search}%"
        q = q.where(
            Release.title.ilike(pattern) | Release.artist.ilike(pattern)
        )

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one()

    q = q.order_by(Release.created_at.desc()).offset((page - 1) * limit).limit(limit)
    rows = await db.execute(q)
    items = [PublicReleaseOut.model_validate(r) for r in rows.scalars().all()]

    return PaginatedReleasesOut(items=items, total=total, page=page, limit=limit)


@router.get(
    "/releases/{release_id}",
    response_model=PublicReleaseWithScan,
    summary="Get release detail",
    description=(
        "Fetch a single release by ID, including its most recent scan summary "
        "(if any scans have been run)."
    ),
)
async def get_release(
    release_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> PublicReleaseWithScan:
    release = await _get_release_for_org(db, release_id, org.id)

    # Latest scan
    scan_result = await db.execute(
        select(Scan)
        .where(Scan.release_id == release_id, Scan.org_id == org.id)
        .order_by(Scan.created_at.desc())
        .limit(1)
    )
    scan = scan_result.scalar_one_or_none()

    return PublicReleaseWithScan(
        release=PublicReleaseOut.model_validate(release),
        scan=PublicScanOut.model_validate(scan) if scan else None,
    )


@router.delete(
    "/releases/{release_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Archive release",
    description=(
        "Soft-delete a release by setting `archived_at`. "
        "Archived releases are hidden from list endpoints by default but can be "
        "retrieved using `include_archived=true`. No scan data is deleted."
    ),
)
async def archive_release(
    release_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> None:
    release = await _get_release_for_org(db, release_id, org.id)
    if release.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Release is already archived")
    release.archived_at = datetime.now(timezone.utc)
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ── Scans ─────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/releases/{release_id}/scan",
    response_model=PublicScanOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger new scan",
    description=(
        "Queue a new QA scan for an existing release. Returns immediately with "
        "`status: queued`. Poll `GET /api/v1/scans/{scan_id}` until "
        "`status` is `complete` or `failed`."
    ),
)
async def trigger_scan(
    release_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> PublicScanOut:
    await _get_release_for_org(db, release_id, org.id)

    scan = Scan(
        id=uuid.uuid4(),
        release_id=release_id,
        org_id=org.id,
        status=ScanStatus.queued,
        layers_run=[],
        created_at=datetime.now(timezone.utc),
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    background_tasks.add_task(
        _run_scan_bg,
        release_id=str(release_id),
        scan_id=str(scan.id),
        org_id=str(org.id),
    )
    return PublicScanOut.model_validate(scan)


@router.get(
    "/scans/{scan_id}",
    response_model=PublicScanOut,
    summary="Get scan summary",
    description=(
        "Return the current scan status and readiness score. "
        "Scores are available once `status` is `complete`. "
        "Grade thresholds: **PASS** ≥ 80, **WARN** ≥ 60, **FAIL** < 60."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "id": "018f2b3c-0000-7000-8000-000000000020",
                        "status": "complete",
                        "readiness_score": 87.5,
                        "grade": "PASS",
                        "critical_count": 0,
                        "warning_count": 3,
                        "info_count": 2,
                    }
                }
            }
        }
    },
)
async def get_scan(
    scan_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> PublicScanOut:
    scan = await _get_scan_for_org(db, scan_id, org.id)
    return PublicScanOut.model_validate(scan)


@router.get(
    "/scans/{scan_id}/results",
    response_model=ScanResultsOut,
    summary="Get scan results",
    description=(
        "Return the full set of QA findings for a scan, with optional filtering. "
        "Results are ordered: critical → warning → info, then alphabetically by layer."
    ),
)
async def get_scan_results(
    scan_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    layer: str | None = Query(
        None,
        description="Filter to a single layer: ddex, metadata, fraud, audio, artwork, enrichment.",
    ),
    severity: str | None = Query(
        None, description="Filter by severity: critical, warning, info."
    ),
    resolved: bool | None = Query(
        None, description="Filter by resolution status."
    ),
) -> ScanResultsOut:
    scan = await _get_scan_for_org(db, scan_id, org.id)

    q = select(ScanResult).where(ScanResult.scan_id == scan_id)
    if layer:
        q = q.where(ScanResult.layer == layer)
    if severity:
        q = q.where(ScanResult.severity == severity)
    if resolved is not None:
        q = q.where(ScanResult.resolved == resolved)
    q = q.order_by(ScanResult.severity.desc(), ScanResult.layer, ScanResult.created_at)

    rows = await db.execute(q)
    results = list(rows.scalars().all())

    return ScanResultsOut(
        scan=PublicScanOut.model_validate(scan),
        results=[PublicScanResultOut.model_validate(r) for r in results],
        total=len(results),
    )


@router.get(
    "/scans/{scan_id}/report",
    summary="Download PDF report",
    description=(
        "Generate and stream a PDF QA report for the completed scan. "
        "Returns application/pdf bytes directly — no S3 or storage required."
    ),
)
async def get_scan_report(
    scan_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
):
    import io
    import re as _re
    from sqlalchemy import select as _select
    from fastapi.responses import StreamingResponse
    from models.scan_result import ScanResult as ScanResultModel, ResultStatus as RS
    from services.reports.generator import ReportData, ReportGenerator, ReportIssue, ReportSuggestion
    from services.scan_orchestrator import calculate_readiness_score
    from services.audio.thresholds import DSP_THRESHOLDS
    from models.release import Release as ReleaseModel

    scan = await _get_scan_for_org(db, scan_id, org.id)

    if scan.status != ScanStatus.complete:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Scan is not yet complete — report available after scan finishes.",
        )

    release_res = await db.execute(_select(ReleaseModel).where(ReleaseModel.id == scan.release_id))
    release = release_res.scalar_one_or_none()
    if not release:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Release not found")

    results_res = await db.execute(
        _select(ScanResultModel)
        .where(ScanResultModel.scan_id == scan_id)
        .order_by(ScanResultModel.severity, ScanResultModel.layer)
    )
    all_results = list(results_res.scalars().all())

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

    layer_order = ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"]
    layer_scores: dict[str, float] = {}
    for layer in layer_order:
        layer_issues = [r for r in all_results if r.layer == layer]
        layer_scores[layer] = calculate_readiness_score(layer_issues)["readiness_score"] if layer_issues else 100.0

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
        scan_id=str(scan_id),
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
    safe_title = _re.sub(r"[^\w\-]", "_", release.title)[:60]
    date_str = (scan.completed_at or scan.created_at).strftime("%Y-%m-%d")
    filename = f"SONGGATE_{safe_title}_{date_str}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch(
    "/scans/{scan_id}/results/{result_id}",
    response_model=PublicScanResultOut,
    summary="Resolve / dismiss a finding",
    description=(
        "Mark a scan result as resolved. Resolved findings are excluded from the "
        "readiness score recalculation on subsequent scans.  "
        "Provide a brief `resolution` note for audit purposes."
    ),
)
async def resolve_result(
    scan_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: ResolveResultIn,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> PublicScanResultOut:
    await _get_scan_for_org(db, scan_id, org.id)

    result = await db.execute(
        select(ScanResult).where(
            ScanResult.id == result_id,
            ScanResult.scan_id == scan_id,
        )
    )
    sr = result.scalar_one_or_none()
    if not sr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Result not found")

    sr.resolved = True
    sr.resolution = payload.resolution
    sr.resolved_by = payload.resolved_by
    sr.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sr)
    return PublicScanResultOut.model_validate(sr)


# ─────────────────────────────────────────────────────────────────────────────
# ── Batch ─────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/batch/scan",
    response_model=BatchJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch scan — create and scan multiple releases (Enterprise only)",
    description=(
        "Accept an array of up to **100 releases**, create them, and immediately "
        "queue a QA scan for each. Returns a `job_id` to track progress via "
        "`GET /api/v1/batch/{job_id}`.  "
        "Ideal for distributors pushing a full catalog at once."
    ),
    responses={
        202: {
            "description": "Batch job created — scans queued",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "018f2b3c-0000-7000-8000-000000000030",
                        "status": "running",
                        "total": 3,
                        "completed": 0,
                        "failed": 0,
                    }
                }
            },
        }
    },
)
async def batch_scan(
    payload: BatchScanIn,
    background_tasks: BackgroundTasks,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> BatchJobOut:
    from dependencies.tier_gate import org_has_feature
    if not org_has_feature(org, "batch_api"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Batch API requires an Enterprise plan.",
        )
    now = datetime.now(timezone.utc)

    # Create all releases + scans in one transaction
    releases: list[Release] = []
    scans: list[Scan] = []
    for item in payload.releases:
        rel = Release(
            id=uuid.uuid4(),
            org_id=org.id,
            external_id=item.external_id,
            title=item.title,
            artist=item.artist,
            upc=item.upc,
            submission_format=item.submission_format,
            status=ReleaseStatus.pending,
            created_at=now,
        )
        sc = Scan(
            id=uuid.uuid4(),
            release_id=rel.id,
            org_id=org.id,
            status=ScanStatus.queued,
            layers_run=[],
            created_at=now,
        )
        db.add(rel)
        db.add(sc)
        releases.append(rel)
        scans.append(sc)

    job = BatchJob(
        id=uuid.uuid4(),
        org_id=org.id,
        status=BatchJobStatus.running,
        total=len(releases),
        completed=0,
        failed_count=0,
        release_ids=[str(r.id) for r in releases],
        scan_ids=[str(s.id) for s in scans],
        label=payload.label,
        created_at=now,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch all scan tasks in the background
    job_id = str(job.id)
    org_id = str(org.id)
    for rel, sc in zip(releases, scans):
        background_tasks.add_task(
            _run_batch_scan_bg,
            release_id=str(rel.id),
            scan_id=str(sc.id),
            org_id=org_id,
            job_id=job_id,
        )

    return _batch_job_out(job)


@router.get(
    "/batch/{job_id}",
    response_model=BatchJobOut,
    summary="Check batch job status",
    description=(
        "Poll this endpoint to track progress of a batch scan job. "
        "`completed + failed` counts up to `total` as individual scans finish."
    ),
)
async def get_batch_job(
    job_id: uuid.UUID,
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> BatchJobOut:
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.org_id == org.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Batch job not found")
    return _batch_job_out(job)


# ─────────────────────────────────────────────────────────────────────────────
# ── Analytics ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/analytics/top-issues",
    response_model=TopIssuesOut,
    summary="Top failing rules this month",
    description=(
        "Return the most frequently triggered rules across all scans in the "
        "current calendar month, ranked by occurrence count. "
        "Use this to identify systemic metadata problems in your catalog."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "period": "2026-04",
                        "items": [
                            {
                                "rule_id": "metadata.missing_isrc",
                                "layer": "metadata",
                                "severity": "critical",
                                "occurrences": 42,
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analytics_top_issues(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100, description="Number of rules to return."),
) -> TopIssuesOut:
    rows = await db.execute(
        text(
            """
            SELECT
                sr.rule_id,
                sr.layer,
                sr.severity,
                COUNT(*) AS occurrences
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE
                s.org_id          = :org_id
                AND sr.created_at >= date_trunc('month', now())
            GROUP BY sr.rule_id, sr.layer, sr.severity
            ORDER BY occurrences DESC
            LIMIT :lim
            """
        ),
        {"org_id": str(org.id), "lim": limit},
    )
    items = [
        TopIssueEntry(
            rule_id=r.rule_id,
            layer=r.layer,
            severity=r.severity,
            occurrences=r.occurrences,
        )
        for r in rows
    ]
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    return TopIssuesOut(period=period, items=items)


@router.get(
    "/analytics/pass-rate",
    response_model=PassRateOut,
    summary="Pass rate over time",
    description=(
        "Daily pass rate for completed scans over the last N days. "
        "A scan **passes** when its grade is `PASS` (readiness score ≥ 80). "
        "Use this time series to track catalog quality trends."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "period_days": 30,
                        "series": [
                            {
                                "date": "2026-04-01",
                                "total_scans": 12,
                                "passed": 9,
                                "pass_rate": 0.75,
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analytics_pass_rate(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=7, le=365, description="Lookback window in days."),
) -> PassRateOut:
    rows = await db.execute(
        text(
            """
            SELECT
                date_trunc('day', completed_at)::date AS day,
                COUNT(*)                              AS total_scans,
                COUNT(*) FILTER (WHERE grade = 'PASS') AS passed
            FROM scans
            WHERE
                org_id       = :org_id
                AND status   = 'complete'
                AND completed_at >= now() - (:days || ' days')::interval
            GROUP BY day
            ORDER BY day
            """
        ),
        {"org_id": str(org.id), "days": days},
    )
    series = [
        PassRatePoint(
            date=str(r.day),
            total_scans=r.total_scans,
            passed=r.passed,
            pass_rate=round(r.passed / r.total_scans, 4) if r.total_scans else 0.0,
        )
        for r in rows
    ]
    return PassRateOut(period_days=days, series=series)


@router.get(
    "/analytics/dsp-breakdown",
    response_model=DSPBreakdownOut,
    summary="Failure rates by DSP",
    description=(
        "Aggregate unresolved issue counts broken down by DSP target. "
        "Results reflect findings from all scans run in the last 90 days. "
        "Issues with no `dsp_targets` (universal issues) are excluded from this view."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "dsp": "spotify",
                                "critical_unresolved": 5,
                                "warning_unresolved": 12,
                                "total_issues": 17,
                            }
                        ]
                    }
                }
            }
        }
    },
)
async def analytics_dsp_breakdown(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> DSPBreakdownOut:
    rows = await db.execute(
        text(
            """
            SELECT
                unnest(sr.dsp_targets)                                        AS dsp,
                COUNT(*) FILTER (WHERE sr.severity = 'critical' AND NOT sr.resolved) AS critical_unresolved,
                COUNT(*) FILTER (WHERE sr.severity = 'warning'  AND NOT sr.resolved) AS warning_unresolved,
                COUNT(*) FILTER (WHERE NOT sr.resolved)                       AS total_issues
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE
                s.org_id         = :org_id
                AND sr.created_at >= now() - interval '90 days'
                AND array_length(sr.dsp_targets, 1) > 0
            GROUP BY dsp
            ORDER BY critical_unresolved DESC, total_issues DESC
            """
        ),
        {"org_id": str(org.id)},
    )
    items = [
        DSPBreakdownEntry(
            dsp=r.dsp,
            critical_unresolved=r.critical_unresolved,
            warning_unresolved=r.warning_unresolved,
            total_issues=r.total_issues,
        )
        for r in rows
    ]
    return DSPBreakdownOut(items=items)


# ─────────────────────────────────────────────────────────────────────────────
# Background task helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _run_scan_bg(release_id: str, scan_id: str, org_id: str) -> None:
    orchestrator = ScanOrchestrator()
    try:
        await orchestrator.run_scan(
            release_id=release_id,
            scan_id=scan_id,
            org_id=org_id,
            dsps=None,
            layers=None,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Background scan failed for scan %s", scan_id
        )


async def _run_batch_scan_bg(
    release_id: str,
    scan_id: str,
    org_id: str,
    job_id: str,
) -> None:
    """
    Run a single scan within a batch job, then increment the job counters.
    Marks the overall batch complete when all scans have finished.
    """
    from database import AsyncSessionLocal
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    succeeded = False
    try:
        await _run_scan_bg(release_id=release_id, scan_id=scan_id, org_id=org_id)
        succeeded = True
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Batch scan failed — job %s scan %s", job_id, scan_id
        )

    # Update batch counters
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(BatchJob).where(BatchJob.id == uuid.UUID(job_id))
            )
            job = result.scalar_one_or_none()
            if job:
                if succeeded:
                    job.completed += 1
                else:
                    job.failed_count += 1

                if job.completed + job.failed_count >= job.total:
                    job.status = (
                        BatchJobStatus.complete
                        if job.failed_count == 0
                        else BatchJobStatus.failed
                    )
                    job.completed_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Failed to update batch job %s counters", job_id
            )


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_release_for_org(
    db: AsyncSession, release_id: uuid.UUID, org_id: uuid.UUID
) -> Release:
    result = await db.execute(
        select(Release).where(
            Release.id == release_id,
            Release.org_id == org_id,
        )
    )
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Release not found")
    return release


async def _get_scan_for_org(
    db: AsyncSession, scan_id: uuid.UUID, org_id: uuid.UUID
) -> Scan:
    result = await db.execute(
        select(Scan).where(
            Scan.id == scan_id,
            Scan.org_id == org_id,
        )
    )
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Scan not found")
    return scan


def _make_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    from config import settings
    import boto3

    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url

    s3 = boto3.client("s3", **kwargs)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key},
        ExpiresIn=expires_in,
    )


def _batch_job_out(job: BatchJob) -> BatchJobOut:
    return BatchJobOut(
        job_id=job.id,
        status=job.status,
        label=job.label,
        total=job.total,
        completed=job.completed,
        failed=job.failed_count,
        release_ids=[str(r) for r in job.release_ids],
        scan_ids=[str(s) for s in job.scan_ids],
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ── Analytics overview ────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_OVERVIEW_TTL = 3600   # 1 hour cache
_SHARE_TTL    = 60 * 60 * 24 * 7   # 7 day share links


@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverview,
    summary="Analytics overview (all panels, single call)",
    description=(
        "Return all analytics data needed for the dashboard in one request. "
        "Results are **cached in Redis for 1 hour** — the underlying queries are "
        "expensive aggregates across the full corpus.\n\n"
        "Panels included:\n"
        "- **aggregate** — totals: releases, issues, resolved count, false-positive rate\n"
        "- **top_issues** — top 10 failing rules all-time (by occurrence count)\n"
        "- **dsp_matrix** — per-DSP pass rate, month-over-month trend, top 3 failures\n"
        "- **fraud_signals** — this month's fraud flag breakdown and confirmation rate\n"
        "- **velocity** — weekly scan count for the last 12 weeks\n\n"
        "Bust the cache by calling `POST /api/v1/analytics/overview/refresh`."
    ),
)
async def analytics_overview(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    from dependencies.tier_gate import org_has_feature
    if not org_has_feature(org, "analytics"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Analytics endpoint requires an Enterprise plan.",
        )
    cache_key = f"analytics:overview:{org.id}"
    redis = await _get_redis()

    if redis is not None:
        cached = await redis.get(cache_key)
        if cached:
            return AnalyticsOverview.model_validate(json.loads(cached))

    overview = await _compute_analytics_overview(db, org.id)

    if redis is not None:
        await redis.setex(cache_key, _OVERVIEW_TTL, overview.model_dump_json())

    return overview


@router.post(
    "/analytics/overview/refresh",
    response_model=AnalyticsOverview,
    status_code=status.HTTP_200_OK,
    summary="Force-refresh analytics cache",
    description=(
        "Immediately recompute and re-cache the analytics overview, bypassing "
        "the 1-hour TTL. Use after resolving a large batch of issues or running "
        "a bulk scan to see up-to-date numbers."
    ),
)
async def analytics_overview_refresh(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    cache_key = f"analytics:overview:{org.id}"
    redis = await _get_redis()
    overview = await _compute_analytics_overview(db, org.id)
    if redis is not None:
        await redis.setex(cache_key, _OVERVIEW_TTL, overview.model_dump_json())
    return overview


@router.post(
    "/analytics/share",
    response_model=ShareTokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public share link",
    description=(
        "Generate a public, read-only share link for a sanitized version of "
        "the analytics overview. Share links are valid for **7 days** and contain "
        "no client-identifying information — org IDs, release titles, and artist "
        "names are stripped. Only aggregate numbers and rule-level breakdowns are "
        "included.\n\n"
        "This is what you open in acquisition conversations."
    ),
)
async def create_share_link(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> ShareTokenOut:
    # Compute fresh (or use cached) overview
    cache_key = f"analytics:overview:{org.id}"
    redis = await _get_redis()

    if redis is not None:
        cached = await redis.get(cache_key)
        if cached:
            overview = AnalyticsOverview.model_validate(json.loads(cached))
        else:
            overview = await _compute_analytics_overview(db, org.id)
            await redis.setex(cache_key, _OVERVIEW_TTL, overview.model_dump_json())
    else:
        overview = await _compute_analytics_overview(db, org.id)

    token = secrets.token_urlsafe(24)
    sanitized = _sanitize_overview(overview)
    serialized = json.dumps(sanitized)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_SHARE_TTL)

    if redis is not None:
        share_key = f"analytics:share:{token}"
        await redis.setex(share_key, _SHARE_TTL, serialized)
    else:
        await _share_token_upsert(db, token, serialized, expires_at)

    return ShareTokenOut(token=token, expires_at=expires_at)


@router.get(
    "/analytics/shared/{token}",
    response_model=AnalyticsOverview,
    summary="Read a shared analytics snapshot (public — no auth)",
    description=(
        "Retrieve a sanitized analytics snapshot using a share token. "
        "No API key is required — this endpoint is publicly accessible. "
        "Tokens expire after 7 days."
    ),
    # Exclude from the authenticated tag group so it appears separately in /docs
)
async def get_shared_analytics(token: str, db: AsyncSession = Depends(get_db)) -> AnalyticsOverview:
    redis = await _get_redis()
    data: str | None = None

    if redis is not None:
        share_key = f"analytics:share:{token}"
        data = await redis.get(share_key)
    else:
        data = await _share_token_lookup(db, token)

    if not data:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Share link not found or expired.",
        )
    return AnalyticsOverview.model_validate(json.loads(data))


# ─────────────────────────────────────────────────────────────────────────────
# Analytics share token — DB fallback when Redis is unavailable
# ─────────────────────────────────────────────────────────────────────────────

_share_table_ensured: bool = False


async def _ensure_share_table(db: AsyncSession) -> None:
    global _share_table_ensured
    if _share_table_ensured:
        return
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS analytics_share_tokens (
            token      TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
    """))
    await db.commit()
    _share_table_ensured = True


async def _share_token_upsert(db: AsyncSession, token: str, data: str, expires_at: datetime) -> None:
    await _ensure_share_table(db)
    await db.execute(text("""
        INSERT INTO analytics_share_tokens (token, data, expires_at)
        VALUES (:token, :data, :expires_at)
        ON CONFLICT (token) DO UPDATE SET data = EXCLUDED.data, expires_at = EXCLUDED.expires_at
    """), {"token": token, "data": data, "expires_at": expires_at})
    await db.commit()


async def _share_token_lookup(db: AsyncSession, token: str) -> str | None:
    await _ensure_share_table(db)
    row = (await db.execute(text("""
        SELECT data FROM analytics_share_tokens
        WHERE token = :token AND expires_at > now()
    """), {"token": token})).fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Redis helper — optional, returns None when unavailable
# ─────────────────────────────────────────────────────────────────────────────

_redis_client: Any = None
_redis_unavailable: bool = False


async def _get_redis() -> Any:
    """Return an aioredis client, or None if Redis is not configured/reachable."""
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        from config import settings
        client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
        await client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        _redis_unavailable = True
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Analytics computation
# ─────────────────────────────────────────────────────────────────────────────

def _rule_label(rule_id: str) -> str:
    """'universal.metadata.upc_required' → 'UPC Required'"""
    parts = rule_id.split(".")
    tail = parts[-1] if parts else rule_id
    return tail.replace("_", " ").title()


async def _compute_analytics_overview(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> AnalyticsOverview:
    now = datetime.now(timezone.utc)
    org_str = str(org_id)

    # ── 1. Aggregate stats ────────────────────────────────────────────────────
    agg = (await db.execute(text("""
        SELECT
            COUNT(DISTINCT s.release_id)               AS total_releases,
            COUNT(sr.id)                               AS total_issues,
            COUNT(sr.id) FILTER (WHERE sr.resolved)    AS issues_resolved
        FROM scans s
        LEFT JOIN scan_results sr ON sr.scan_id = s.id
        WHERE s.org_id = :org_id
    """), {"org_id": org_str})).mappings().one()

    total_issues   = int(agg["total_issues"] or 0)
    issues_resolved = int(agg["issues_resolved"] or 0)
    false_positive_rate = round(
        (issues_resolved / total_issues * 100) if total_issues else 0.0, 1
    )
    aggregate = AggregateStats(
        total_releases_scanned=int(agg["total_releases"] or 0),
        total_issues_found=total_issues,
        issues_resolved=issues_resolved,
        false_positive_rate=false_positive_rate,
    )

    # ── 2. Top 10 rules all-time ──────────────────────────────────────────────
    top_rows = (await db.execute(text("""
        SELECT sr.rule_id, sr.layer, sr.severity, COUNT(*) AS occurrences
        FROM scan_results sr
        JOIN scans s ON s.id = sr.scan_id
        WHERE s.org_id = :org_id
        GROUP BY sr.rule_id, sr.layer, sr.severity
        ORDER BY occurrences DESC
        LIMIT 10
    """), {"org_id": org_str})).mappings().all()

    top_issues = [
        TopIssueItem(
            rule_id=r["rule_id"],
            rule_label=_rule_label(r["rule_id"]),
            layer=r["layer"],
            severity=r["severity"],
            occurrences=int(r["occurrences"]),
        )
        for r in top_rows
    ]

    # ── 3. DSP matrix ─────────────────────────────────────────────────────────
    dsp_matrix = await _compute_dsp_matrix(db, org_str)

    # ── 4. Fraud signals (this calendar month) ────────────────────────────────
    fraud_rows = (await db.execute(text("""
        SELECT
            sr.rule_id,
            COUNT(*)                            AS total_flags,
            COUNT(*) FILTER (WHERE sr.resolved) AS confirmed
        FROM scan_results sr
        JOIN scans s ON s.id = sr.scan_id
        WHERE s.org_id = :org_id
          AND sr.layer = 'fraud'
          AND sr.created_at >= date_trunc('month', now())
        GROUP BY sr.rule_id
        ORDER BY total_flags DESC
    """), {"org_id": org_str})).mappings().all()

    fraud_by_type = [
        FraudSignalItem(
            signal=_rule_label(r["rule_id"]),
            rule_id=r["rule_id"],
            total_flags=int(r["total_flags"]),
            confirmed=int(r["confirmed"]),
        )
        for r in fraud_rows
    ]
    total_fraud   = sum(f.total_flags for f in fraud_by_type)
    confirmed_fraud = sum(f.confirmed for f in fraud_by_type)
    dismissed_fraud = total_fraud - confirmed_fraud
    fraud_signals = FraudSummary(
        total_flags_this_month=total_fraud,
        confirmed=confirmed_fraud,
        dismissed=dismissed_fraud,
        confirmation_rate=round(
            (confirmed_fraud / total_fraud * 100) if total_fraud else 0.0, 1
        ),
        by_type=fraud_by_type,
    )

    # ── 5. Velocity (weekly scan count, last 12 weeks) ────────────────────────
    vel_rows = (await db.execute(text("""
        SELECT
            date_trunc('week', created_at)::date AS week_start,
            COUNT(*)                             AS scans
        FROM scans
        WHERE org_id  = :org_id
          AND created_at >= now() - interval '12 weeks'
        GROUP BY week_start
        ORDER BY week_start
    """), {"org_id": org_str})).mappings().all()

    velocity = [
        VelocityPoint(week=str(r["week_start"]), scans=int(r["scans"]))
        for r in vel_rows
    ]

    return AnalyticsOverview(
        aggregate=aggregate,
        top_issues=top_issues,
        dsp_matrix=dsp_matrix,
        fraud_signals=fraud_signals,
        velocity=velocity,
        cached_at=now,
        cache_ttl_seconds=_OVERVIEW_TTL,
    )


async def _compute_dsp_matrix(
    db: AsyncSession, org_str: str
) -> list[DSPMatrixRow]:
    """
    Per-DSP pass rate for the current and previous calendar month,
    plus top 3 failing rules per DSP.
    """
    # Pass rates by DSP and month
    rate_rows = (await db.execute(text("""
        WITH dsp_scans AS (
            SELECT
                unnest(sr.dsp_targets) AS dsp,
                s.grade,
                date_trunc('month', s.completed_at) AS month
            FROM scan_results sr
            JOIN scans s ON s.id = sr.scan_id
            WHERE s.org_id  = :org_id
              AND s.status  = 'complete'
              AND s.completed_at >= now() - interval '2 months'
              AND array_length(sr.dsp_targets, 1) > 0
            GROUP BY dsp, s.id, s.grade, month
        ),
        monthly AS (
            SELECT
                dsp,
                month,
                COUNT(*)                              AS total,
                COUNT(*) FILTER (WHERE grade = 'PASS') AS passed
            FROM dsp_scans
            GROUP BY dsp, month
        )
        SELECT
            curr.dsp,
            curr.total                                       AS current_scans,
            ROUND(curr.passed::numeric / NULLIF(curr.total,0) * 100, 1) AS current_rate,
            ROUND(prev.passed::numeric / NULLIF(prev.total,0) * 100, 1) AS prev_rate
        FROM monthly curr
        LEFT JOIN monthly prev
               ON curr.dsp = prev.dsp
              AND prev.month = date_trunc('month', now()) - interval '1 month'
        WHERE curr.month = date_trunc('month', now())
        ORDER BY current_rate ASC
    """), {"org_id": org_str})).mappings().all()

    if not rate_rows:
        return []

    # Top failures per DSP
    failure_rows = (await db.execute(text("""
        SELECT
            unnest(sr.dsp_targets) AS dsp,
            sr.rule_id,
            COUNT(*) AS occurrences
        FROM scan_results sr
        JOIN scans s ON s.id = sr.scan_id
        WHERE s.org_id   = :org_id
          AND NOT sr.resolved
          AND sr.created_at >= now() - interval '30 days'
          AND array_length(sr.dsp_targets, 1) > 0
        GROUP BY dsp, sr.rule_id
        ORDER BY occurrences DESC
    """), {"org_id": org_str})).mappings().all()

    # Index top 3 failures per DSP
    failures_by_dsp: dict[str, list[str]] = {}
    for r in failure_rows:
        dsp = r["dsp"]
        if dsp not in failures_by_dsp:
            failures_by_dsp[dsp] = []
        if len(failures_by_dsp[dsp]) < 3:
            failures_by_dsp[dsp].append(r["rule_id"])

    return [
        DSPMatrixRow(
            dsp=r["dsp"],
            avg_pass_rate=float(r["current_rate"] or 0),
            trend=round(
                float(r["current_rate"] or 0) - float(r["prev_rate"] or 0), 1
            ),
            total_scans=int(r["current_scans"]),
            top_failures=failures_by_dsp.get(r["dsp"], []),
        )
        for r in rate_rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Usage endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/usage/summary",
    summary="API usage summary",
    description=(
        "Return aggregate API call counts and error rates for the last 30 days. "
        "Grouped by endpoint and HTTP method."
    ),
)
async def get_usage_summary(
    org: OrgDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    window_start = datetime.now(timezone.utc) - timedelta(days=30)

    rows = await db.execute(
        text("""
            SELECT
                endpoint,
                method,
                COUNT(*)                                                    AS total_calls,
                COUNT(*) FILTER (WHERE status_code >= 400)                 AS error_calls,
                ROUND(AVG(latency_ms)::numeric, 1)                        AS avg_latency_ms,
                MIN(created_at)                                            AS first_call,
                MAX(created_at)                                            AS last_call
            FROM api_usage_events
            WHERE org_id = :org_id
              AND created_at >= :since
            GROUP BY endpoint, method
            ORDER BY total_calls DESC
        """),
        {"org_id": str(org.id), "since": window_start.isoformat()},
    )

    totals = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                    AS total_calls,
                COUNT(*) FILTER (WHERE status_code >= 400)                 AS total_errors,
                COUNT(*) FILTER (WHERE status_code = 429)                  AS rate_limited
            FROM api_usage_events
            WHERE org_id = :org_id
              AND created_at >= :since
        """),
        {"org_id": str(org.id), "since": window_start.isoformat()},
    )
    t = dict(totals.mappings().one())

    return {
        "period_days": 30,
        "total_calls":   int(t["total_calls"]   or 0),
        "total_errors":  int(t["total_errors"]  or 0),
        "rate_limited":  int(t["rate_limited"]  or 0),
        "by_endpoint": [
            {
                "endpoint":       r["endpoint"],
                "method":         r["method"],
                "total_calls":    int(r["total_calls"]),
                "error_calls":    int(r["error_calls"]),
                "avg_latency_ms": float(r["avg_latency_ms"] or 0),
                "first_call":     r["first_call"].isoformat() if r["first_call"] else None,
                "last_call":      r["last_call"].isoformat()  if r["last_call"]  else None,
            }
            for r in rows.mappings().all()
        ],
    }


@router.get(
    "/usage/history",
    summary="Daily API usage history",
    description="Return daily call counts for the last N days (default 30).",
)
async def get_usage_history(
    org: OrgDep,
    days: int = Query(30, ge=1, le=90, description="Number of days to return"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    window_start = datetime.now(timezone.utc) - timedelta(days=days)

    rows = await db.execute(
        text("""
            SELECT
                DATE_TRUNC('day', created_at AT TIME ZONE 'UTC')::date  AS day,
                COUNT(*)                                                  AS total_calls,
                COUNT(*) FILTER (WHERE status_code >= 400)               AS error_calls,
                COUNT(*) FILTER (WHERE status_code = 429)                AS rate_limited
            FROM api_usage_events
            WHERE org_id = :org_id
              AND created_at >= :since
            GROUP BY 1
            ORDER BY 1 ASC
        """),
        {"org_id": str(org.id), "since": window_start.isoformat()},
    )

    return {
        "period_days": days,
        "history": [
            {
                "date":        str(r["day"]),
                "total_calls": int(r["total_calls"]),
                "error_calls": int(r["error_calls"]),
                "rate_limited": int(r["rate_limited"]),
            }
            for r in rows.mappings().all()
        ],
    }


def _sanitize_overview(overview: AnalyticsOverview) -> dict[str, Any]:
    """
    Return a JSON-serializable dict safe for public sharing.
    Strips nothing from aggregates (no client names exist in this payload).
    Adds a data_as_of marker so the recipient knows when it was computed.
    """
    d = json.loads(overview.model_dump_json())
    d["data_as_of"] = overview.cached_at.isoformat()
    d["is_sanitized"] = True
    # Strip cache metadata that's internal
    d.pop("cache_ttl_seconds", None)
    return d
