import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.release import Release
from schemas.release import ReleaseCreate


class ReleaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_org(self, org_id: uuid.UUID) -> list[Release]:
        result = await self.db.execute(
            select(Release)
            .where(Release.org_id == org_id)
            .order_by(Release.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_org(self, release_id: str, org_id: uuid.UUID) -> Release | None:
        result = await self.db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, payload: ReleaseCreate, org_id: uuid.UUID) -> Release:
        release = Release(
            org_id=org_id,
            title=payload.title,
            artist=payload.artist,
            upc=payload.upc,
            release_date=payload.release_date,
            submission_format=payload.submission_format,
            external_id=payload.external_id,
        )
        self.db.add(release)
        await self.db.commit()
        await self.db.refresh(release)
        return release

    async def attach_artifact(self, release_id: str, file: UploadFile) -> dict:
        # TODO: upload to S3 via boto3 and persist artifact_url
        return {"detail": "artifact upload not yet implemented", "filename": file.filename}

    async def delete(self, release_id: str) -> None:
        result = await self.db.execute(
            select(Release).where(Release.id == release_id)
        )
        release = result.scalar_one_or_none()
        if release:
            await self.db.delete(release)
            await self.db.commit()
