"""
S3 helpers: presigned PUT URL generation and object key construction.

Bucket layout
─────────────
ropqa/{org_id}/releases/{release_id}/package/   ← DDEX .zip / .xml
ropqa/{org_id}/releases/{release_id}/audio/     ← .wav / .flac / .aiff / .mp3
ropqa/{org_id}/releases/{release_id}/artwork/   ← .jpg / .png / .tiff
ropqa/{org_id}/releases/{release_id}/reports/   ← generated QA reports

S3 CORS note
────────────
For client-side PUT uploads the bucket must allow PUT from your frontend origin:
  AllowedHeaders: ["*"]
  AllowedMethods: ["PUT"]
  AllowedOrigins: ["http://localhost:3000", "https://your-domain.com"]
  ExposeHeaders: ["ETag"]
"""

from __future__ import annotations

import re
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from config import settings

_PRESIGN_EXPIRES = 3600  # seconds

FOLDER_BY_TYPE: dict[str, str] = {
    "ddex_package": "package",
    "audio": "audio",
    "artwork": "artwork",
    "report": "reports",
}


def _get_s3_client():
    kwargs: dict = {
        "region_name": settings.aws_region,
        "config": Config(signature_version="s3v4"),
    }
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    return boto3.client("s3", **kwargs)


def _safe_filename(name: str) -> str:
    """Strip path components and replace non-alphanumeric chars (except . - _)."""
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "upload"


def build_object_key(
    org_id: str | uuid.UUID,
    release_id: str | uuid.UUID,
    file_type: str,
    filename: str,
) -> str:
    """
    Return the canonical S3 key for a release artifact.

    e.g. ropqa/<org_id>/releases/<release_id>/audio/track01.wav
    """
    folder = FOLDER_BY_TYPE.get(file_type, file_type)
    return (
        f"ropqa/{org_id}/releases/{release_id}"
        f"/{folder}/{_safe_filename(filename)}"
    )


def s3_public_url(object_key: str) -> str:
    """Return the https URL for an object (bucket must be public or use CDN)."""
    if settings.s3_endpoint_url:
        return f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{object_key}"
    return (
        f"https://{settings.s3_bucket}.s3.{settings.aws_region}"
        f".amazonaws.com/{object_key}"
    )


def generate_presigned_put(object_key: str, content_type: str) -> str:
    """
    Generate a presigned S3 PUT URL.

    The client must send:
      PUT <upload_url>
      Content-Type: <content_type>
      (body: raw file bytes)
    """
    if not settings.s3_bucket:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3_BUCKET is not configured",
        )
    try:
        client = _get_s3_client()
        url: str = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=_PRESIGN_EXPIRES,
        )
        return url
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not generate presigned URL: {exc}",
        )
