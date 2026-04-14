from typing import Literal
from pydantic import BaseModel

FileType = Literal["ddex_package", "audio", "artwork"]


class PresignRequest(BaseModel):
    filename: str
    content_type: str
    release_id: str
    file_type: FileType


class PresignResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int


class ConfirmRequest(BaseModel):
    object_key: str
    release_id: str
    file_type: FileType


class ConfirmResponse(BaseModel):
    release_id: str
    object_key: str
    artifact_url: str
    scan_id: str | None = None
    message: str
