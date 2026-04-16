from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.release import ReleaseCreate, ReleaseRead
from services.release_service import ReleaseService

router = APIRouter()


@router.get("/", response_model=list[ReleaseRead])
async def list_releases(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    rows = await db.execute(
        text("""
            SELECT
                r.id, r.org_id, r.external_id, r.title, r.artist,
                r.upc, r.release_date, r.submission_format,
                r.raw_package_url, r.status, r.created_at,
                s.id              AS latest_scan_id,
                s.grade           AS latest_scan_grade,
                s.readiness_score AS latest_scan_score
            FROM releases r
            LEFT JOIN LATERAL (
                SELECT id, grade, readiness_score
                FROM scans
                WHERE release_id = r.id
                ORDER BY created_at DESC
                LIMIT 1
            ) s ON TRUE
            WHERE r.org_id = :org_id
            ORDER BY r.created_at DESC
        """),
        {"org_id": str(org.id)},
    )
    return [ReleaseRead.model_validate(dict(row)) for row in rows.mappings().all()]


@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(
    release_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    rows = await db.execute(
        text("""
            SELECT
                r.id, r.org_id, r.external_id, r.title, r.artist,
                r.upc, r.release_date, r.submission_format,
                r.raw_package_url, r.status, r.created_at,
                s.id              AS latest_scan_id,
                s.grade           AS latest_scan_grade,
                s.readiness_score AS latest_scan_score
            FROM releases r
            LEFT JOIN LATERAL (
                SELECT id, grade, readiness_score
                FROM scans
                WHERE release_id = r.id
                ORDER BY created_at DESC
                LIMIT 1
            ) s ON TRUE
            WHERE r.id = :release_id
              AND r.org_id = :org_id
        """),
        {"release_id": release_id, "org_id": str(org.id)},
    )
    row = rows.mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return ReleaseRead.model_validate(dict(row))


@router.post("/", response_model=ReleaseRead, status_code=status.HTTP_201_CREATED)
async def create_release(
    payload: ReleaseCreate,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    return await ReleaseService(db).create(payload, org_id=org.id)


@router.post("/{release_id}/upload")
async def upload_artifact(
    release_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    release = await ReleaseService(db).get_for_org(release_id, org.id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return await ReleaseService(db).attach_artifact(release_id, file)


@router.delete("/{release_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_release(
    release_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    release = await ReleaseService(db).get_for_org(release_id, org.id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    await ReleaseService(db).delete(release_id)
