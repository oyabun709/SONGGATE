from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.report import ReportRead
from services.report_service import ReportService

router = APIRouter()


@router.get("/", response_model=list[ReportRead])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    return await ReportService(db).list_all()


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    report = await ReportService(db).get(report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report
