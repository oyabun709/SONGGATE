"""
Upload router — presigned S3 PUT URLs and upload confirmation.

Flow
────
1. Client calls POST /uploads/presign  → receives { upload_url, object_key }
2. Client PUTs the file directly to S3 using upload_url (no proxy through API)
3. Client calls POST /uploads/confirm  → release updated, scan queued
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from models.release import Release, ReleaseStatus
from models.scan import Scan, ScanStatus
from schemas.upload import (
    ConfirmRequest,
    ConfirmResponse,
    PresignRequest,
    PresignResponse,
)
from services.s3_service import (
    _PRESIGN_EXPIRES,
    build_object_key,
    generate_presigned_put,
    s3_public_url,
)
from tasks.pipeline_tasks import run_pipeline

router = APIRouter()


async def _get_release_for_org(
    release_id: str,
    org_id: uuid.UUID,
    db: AsyncSession,
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


@router.post("/presign", response_model=PresignResponse)
async def presign_upload(
    payload: PresignRequest,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
) -> PresignResponse:
    """
    Generate a presigned S3 PUT URL for a release artifact.

    The caller must include the exact Content-Type header when issuing the PUT
    to S3, otherwise the request will fail signature validation.
    """
    # Verify the release belongs to this org before handing out a URL
    await _get_release_for_org(payload.release_id, org.id, db)

    object_key = build_object_key(
        org_id=org.id,
        release_id=payload.release_id,
        file_type=payload.file_type,
        filename=payload.filename,
    )
    upload_url = generate_presigned_put(object_key, payload.content_type)

    return PresignResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=_PRESIGN_EXPIRES,
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_upload(
    payload: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
) -> ConfirmResponse:
    """
    Mark an S3 upload complete, persist the artifact URL, and queue a scan.

    For ddex_package and audio, a new Scan is created and the pipeline task is
    dispatched to Celery.  Artwork uploads are acknowledged without triggering
    a full re-scan (they can be included in the next package scan).
    """
    release = await _get_release_for_org(payload.release_id, org.id, db)

    # Verify the object_key is scoped to this org/release (prevents spoofing)
    expected_prefix = f"ropqa/{org.id}/releases/{release.id}/"
    if not payload.object_key.startswith(expected_prefix):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="object_key does not belong to this release",
        )

    artifact_url = s3_public_url(payload.object_key)
    scan_id: str | None = None

    if payload.file_type == "ddex_package":
        release.raw_package_url = artifact_url
        release.status = ReleaseStatus.ingesting
        scan = await _create_scan(release, org.id, db)
        scan_id = str(scan.id)
        run_pipeline.delay(str(scan.id), str(release.id))

    elif payload.file_type == "audio":
        # Persist at release level for now; track-level attachment happens
        # after DDEX parse assigns the ISRC → track mapping.
        if not release.raw_package_url:
            # Audio-only delivery (no DDEX); treat this as the package too
            release.raw_package_url = artifact_url
            release.status = ReleaseStatus.ingesting
            scan = await _create_scan(release, org.id, db)
            scan_id = str(scan.id)
            run_pipeline.delay(str(scan.id), str(release.id))

    elif payload.file_type == "artwork":
        # No scan trigger for artwork alone — folded into the next package scan
        pass

    await db.commit()

    return ConfirmResponse(
        release_id=str(release.id),
        object_key=payload.object_key,
        artifact_url=artifact_url,
        scan_id=scan_id,
        message="Upload confirmed"
        + (f"; scan {scan_id} queued" if scan_id else ""),
    )


async def _create_scan(
    release: Release,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> Scan:
    scan = Scan(
        id=uuid.uuid4(),
        release_id=release.id,
        org_id=org_id,
        status=ScanStatus.queued,
        layers_run=[],
        created_at=datetime.now(timezone.utc),
    )
    db.add(scan)
    await db.flush()  # populate scan.id before the caller uses it
    return scan
