from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.release import Release
from schemas.release import ReleaseCreate


class ReleaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[Release]:
        result = await self.db.execute(select(Release).order_by(Release.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, release_id: str) -> Release | None:
        return await self.db.get(Release, release_id)

    async def create(self, payload: ReleaseCreate) -> Release:
        release = Release(name=payload.name, version=payload.version)
        self.db.add(release)
        await self.db.commit()
        await self.db.refresh(release)
        return release

    async def attach_artifact(self, release_id: str, file: UploadFile) -> dict:
        # TODO: upload to S3 via boto3 and persist artifact_url
        return {"detail": "artifact upload not yet implemented", "filename": file.filename}

    async def delete(self, release_id: str) -> None:
        release = await self.get(release_id)
        if release:
            await self.db.delete(release)
            await self.db.commit()
