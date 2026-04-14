from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.release import ReleaseCreate, ReleaseRead
from services.release_service import ReleaseService

router = APIRouter()


@router.get("/", response_model=list[ReleaseRead])
async def list_releases(db: AsyncSession = Depends(get_db)):
    return await ReleaseService(db).list_all()


@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(release_id: str, db: AsyncSession = Depends(get_db)):
    release = await ReleaseService(db).get(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return release


@router.post("/", response_model=ReleaseRead, status_code=status.HTTP_201_CREATED)
async def create_release(payload: ReleaseCreate, db: AsyncSession = Depends(get_db)):
    return await ReleaseService(db).create(payload)


@router.post("/{release_id}/upload")
async def upload_artifact(
    release_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    return await ReleaseService(db).attach_artifact(release_id, file)


@router.delete("/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_release(release_id: str, db: AsyncSession = Depends(get_db)):
    await ReleaseService(db).delete(release_id)
