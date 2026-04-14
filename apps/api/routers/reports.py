from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.scan import ScanRead
from schemas.scan_result import ScanDetailRead, ResolveRequest, ScanResultRead
from services.report_service import ReportService

router = APIRouter()


@router.get("/", response_model=list[ScanRead])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """List completed scans (reports) for this org."""
    return await ReportService(db).list_for_org(org.id)


@router.get("/{scan_id}", response_model=ScanDetailRead)
async def get_report(
    scan_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Return a completed scan with its full ScanResult corpus."""
    result = await ReportService(db).get_with_results(scan_id, org.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    scan, results = result
    # Compose ScanDetailRead manually since results is a separate query
    detail = ScanDetailRead.model_validate(scan)
    detail.results = [ScanResultRead.model_validate(r) for r in results]
    return detail


@router.patch("/{scan_id}/results/{result_id}/resolve", response_model=ScanResultRead)
async def resolve_result(
    scan_id: str,
    result_id: str,
    payload: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Mark a ScanResult as resolved with a resolution note."""
    sr = await ReportService(db).resolve_result(
        result_id=result_id,
        org_id=org.id,
        resolution=payload.resolution,
        resolved_by=payload.resolved_by,
    )
    if not sr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    return sr
