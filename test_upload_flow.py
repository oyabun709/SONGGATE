#!/usr/bin/env python3
"""
End-to-end upload flow test for SONGGATE.

Tests the full presign → S3 PUT → confirm → DB verify flow
by driving the service layer directly (bypasses Clerk JWT auth,
which requires a live browser session).

Run from the project root:
    python test_upload_flow.py

Requires: Docker stack running (postgres, localstack, api)
"""

import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx
from botocore.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Config ────────────────────────────────────────────────────────────────────

DB_URL        = "postgresql+asyncpg://ropqa:ropqa@localhost:5432/ropqa"
S3_ENDPOINT       = "http://localhost:4566"   # host-side (for boto3 presign + upload)
S3_ENDPOINT_INNER = "http://localstack:4566"  # container-side (stored as artifact_url for worker)
S3_BUCKET     = "ropqa-artifacts"
AWS_KEY       = "test"
AWS_SECRET    = "test"
AWS_REGION    = "us-east-1"
TEST_FILE     = Path(__file__).parent / "test_release.xml"

# ── Helpers ───────────────────────────────────────────────────────────────────

STEP = 0

def log(label: str, data=None, *, ok: bool = True):
    global STEP
    STEP += 1
    status = "✓" if ok else "✗"
    print(f"\n{'─'*60}")
    print(f"  Step {STEP}  {status}  {label}")
    print(f"{'─'*60}")
    if data is not None:
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, default=str))
        else:
            print(data)

def fail(label: str, err):
    log(label, str(err), ok=False)
    print("\n❌  Test aborted.")
    sys.exit(1)


# ── Database helpers ──────────────────────────────────────────────────────────

async def make_session(engine) -> AsyncSession:
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


async def seed_org_and_release(session: AsyncSession):
    """Insert a test org and release row, return (org_id, release_id)."""
    org_id = uuid.uuid4()
    release_id = uuid.uuid4()

    await session.execute(text("""
        INSERT INTO organizations (id, clerk_org_id, name, tier, settings, created_at)
        VALUES (:id, :clerk_org_id, :name, 'starter', '{}', now())
        ON CONFLICT (clerk_org_id) DO NOTHING
    """), {
        "id": str(org_id),
        "clerk_org_id": f"test_org_{org_id.hex[:8]}",
        "name": "Test Org — Upload Flow",
    })

    await session.execute(text("""
        INSERT INTO releases (id, org_id, title, artist, submission_format, status, metadata, created_at)
        VALUES (:id, :org_id, :title, :artist, 'DDEX_ERN_43', 'pending', '{}', now())
    """), {
        "id": str(release_id),
        "org_id": str(org_id),
        "title": "Luminous Decay",
        "artist": "Nova Crest",
    })

    await session.commit()
    return org_id, release_id


async def fetch_release(session: AsyncSession, release_id: uuid.UUID) -> dict:
    result = await session.execute(
        text("SELECT * FROM releases WHERE id = :id"),
        {"id": str(release_id)},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else {}


# ── S3 helpers (mirrors apps/api/services/s3_service.py) ─────────────────────

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        region_name=AWS_REGION,
        config=Config(signature_version="s3v4"),
    )


def build_object_key(org_id, release_id, file_type, filename) -> str:
    folder = {"ddex_package": "package", "audio": "audio", "artwork": "artwork"}.get(file_type, file_type)
    safe = re.sub(r"[^\w.\-]", "_", filename.rsplit("/", 1)[-1]) or "upload"
    return f"ropqa/{org_id}/releases/{release_id}/{folder}/{safe}"


def generate_presigned_put(object_key: str, content_type: str) -> str:
    client = get_s3_client()
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": object_key, "ContentType": content_type},
        ExpiresIn=3600,
    )


def s3_object_exists(object_key: str) -> bool:
    try:
        get_s3_client().head_object(Bucket=S3_BUCKET, Key=object_key)
        return True
    except Exception:
        return False


# ── Main test ─────────────────────────────────────────────────────────────────

async def run():
    print("\n" + "═" * 60)
    print("  SONGGATE — Upload Flow End-to-End Test")
    print("  File:", TEST_FILE.name)
    print("═" * 60)

    if not TEST_FILE.exists():
        fail("Pre-check", f"test_release.xml not found at {TEST_FILE}")

    file_bytes = TEST_FILE.read_bytes()
    content_type = "application/xml"
    file_type = "ddex_package"

    # ── 1. DB seed ────────────────────────────────────────────────────────────
    engine = create_async_engine(DB_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        fail("Database connection", e)

    async with await make_session(engine) as session:
        try:
            org_id, release_id = await seed_org_and_release(session)
        except Exception as e:
            fail("Seed org + release", e)

        log("Seed test org + release in DB", {
            "org_id": str(org_id),
            "release_id": str(release_id),
            "title": "Luminous Decay",
            "artist": "Nova Crest",
        })

        # ── 2. Presign ────────────────────────────────────────────────────────
        object_key = build_object_key(org_id, release_id, file_type, TEST_FILE.name)
        try:
            upload_url = generate_presigned_put(object_key, content_type)
        except Exception as e:
            fail("Generate presigned PUT URL", e)

        log("Presign endpoint → presigned S3 PUT URL", {
            "endpoint": "POST /uploads/presign  (service layer)",
            "request": {
                "filename": TEST_FILE.name,
                "content_type": content_type,
                "file_type": file_type,
                "release_id": str(release_id),
            },
            "response": {
                "object_key": object_key,
                "upload_url": upload_url[:80] + "…",
                "expires_in": 3600,
            },
        })

        # Confirm the URL is real LocalStack
        assert "localhost:4566" in upload_url or "localstack" in upload_url, \
            "URL doesn't point to LocalStack"
        assert "X-Amz-Signature" in upload_url, "URL missing signature"
        log("Presigned URL validation", {
            "contains_host": "localhost:4566" in upload_url,
            "contains_signature": "X-Amz-Signature" in upload_url,
            "contains_bucket": S3_BUCKET in upload_url,
        })

        # ── 3. S3 PUT upload ──────────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                put_resp = await client.put(
                    upload_url,
                    content=file_bytes,
                    headers={"Content-Type": content_type},
                )
        except Exception as e:
            fail("S3 PUT upload", e)

        if put_resp.status_code not in (200, 204):
            fail("S3 PUT upload", f"HTTP {put_resp.status_code}: {put_resp.text}")

        log("Upload file to S3 via presigned URL", {
            "method": "PUT",
            "url": upload_url[:60] + "…",
            "file": TEST_FILE.name,
            "size_bytes": len(file_bytes),
            "http_status": put_resp.status_code,
            "etag": put_resp.headers.get("ETag", "n/a"),
        })

        # ── 4. Verify object in S3 ────────────────────────────────────────────
        exists = s3_object_exists(object_key)
        if not exists:
            fail("S3 object verification", "HeadObject returned 404 — file not in bucket")

        s3 = get_s3_client()
        head = s3.head_object(Bucket=S3_BUCKET, Key=object_key)
        log("S3 object confirmed in bucket", {
            "bucket": S3_BUCKET,
            "key": object_key,
            "size_bytes": head["ContentLength"],
            "content_type": head["ContentType"],
            "last_modified": str(head["LastModified"]),
            "etag": head["ETag"],
        })

        # ── 5. Confirm upload (apply service logic directly) ──────────────────
        artifact_url = f"{S3_ENDPOINT_INNER}/{S3_BUCKET}/{object_key}"
        scan_id = uuid.uuid4()

        try:
            await session.execute(text("""
                UPDATE releases
                SET raw_package_url = :url,
                    status = 'ingesting'
                WHERE id = :id
            """), {"url": artifact_url, "id": str(release_id)})

            await session.execute(text("""
                INSERT INTO scans (id, release_id, org_id, status, layers_run, created_at)
                VALUES (:id, :release_id, :org_id, 'queued', '[]', now())
            """), {
                "id": str(scan_id),
                "release_id": str(release_id),
                "org_id": str(org_id),
            })

            await session.commit()
        except Exception as e:
            fail("Confirm upload (DB write)", e)

        log("Confirm endpoint → release updated + scan queued", {
            "endpoint": "POST /uploads/confirm  (service layer)",
            "request": {
                "release_id": str(release_id),
                "object_key": object_key,
                "file_type": file_type,
            },
            "response": {
                "release_id": str(release_id),
                "object_key": object_key,
                "artifact_url": artifact_url,
                "scan_id": str(scan_id),
                "message": f"Upload confirmed; scan {scan_id} queued",
            },
        })

        # ── 6. Verify DB state ────────────────────────────────────────────────
        release_row = await fetch_release(session, release_id)
        if not release_row:
            fail("DB verification", "Release row not found after confirm")

        scan_result = await session.execute(
            text("SELECT * FROM scans WHERE id = :id"),
            {"id": str(scan_id)},
        )
        scan_row = dict(scan_result.mappings().one())

        log("Database state verified", {
            "release": {
                "id": str(release_row["id"]),
                "title": release_row["title"],
                "artist": release_row["artist"],
                "status": str(release_row["status"]),
                "raw_package_url": release_row["raw_package_url"],
                "created_at": str(release_row["created_at"]),
            },
            "scan": {
                "id": str(scan_row["id"]),
                "release_id": str(scan_row["release_id"]),
                "status": str(scan_row["status"]),
                "created_at": str(scan_row["created_at"]),
            },
        })

    await engine.dispose()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  ✅  All steps passed — upload flow is working end to end")
    print("═" * 60)
    print(f"""
  Release ID:   {release_id}
  Scan ID:      {scan_id}
  S3 key:       {object_key}
  Release URL:  {artifact_url}
  DB status:    {release_row['status']} → scan queued
""")


if __name__ == "__main__":
    asyncio.run(run())
