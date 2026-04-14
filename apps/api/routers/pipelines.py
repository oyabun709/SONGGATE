from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.pipeline import PipelineRead
from services.pipeline_service import PipelineService

router = APIRouter()


@router.get("/", response_model=list[PipelineRead])
async def list_pipelines(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    return await PipelineService(db).list_all()


@router.get("/{pipeline_id}", response_model=PipelineRead)
async def get_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    pipeline = await PipelineService(db).get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return pipeline


@router.post("/{pipeline_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    await PipelineService(db).cancel(pipeline_id)
    return {"detail": "cancellation requested"}
