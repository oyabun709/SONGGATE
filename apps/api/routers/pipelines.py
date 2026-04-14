from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.scan import ScanRead
from services.pipeline_service import PipelineService

router = APIRouter()


@router.get("/", response_model=list[ScanRead])
async def list_pipelines(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    return await PipelineService(db).list_for_org(org.id)


@router.get("/{scan_id}", response_model=ScanRead)
async def get_pipeline(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    scan = await PipelineService(db).get_for_org(scan_id, org.id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return scan


@router.post("/{scan_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_pipeline(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    scan = await PipelineService(db).cancel(scan_id, org.id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return {"detail": "cancellation requested", "scan_id": scan_id}
