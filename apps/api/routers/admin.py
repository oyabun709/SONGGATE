"""Admin-only endpoints for viewing all orgs and managing trial access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.admin import require_admin, require_admin_secret
from models.organization import Organization, OrgTier

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

# Second router — same /admin prefix, authenticated by X-Admin-Secret header
# (machine-to-machine; no Clerk JWT required).
secret_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_secret)])


# ── Response schemas ───────────────────────────────────────────────────────────

class OrgSummary(BaseModel):
    id: str
    clerk_org_id: str
    name: str
    tier: str
    scan_count_current_period: int
    scan_limit: int
    is_trial: bool
    created_at: datetime
    total_scans: int
    total_releases: int

    model_config = {"from_attributes": True}


class OrgScanItem(BaseModel):
    id: str
    release_id: str
    release_title: str
    release_artist: str
    status: str
    grade: str | None
    readiness_score: float | None
    critical_count: int
    warning_count: int
    info_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TrialGrantRequest(BaseModel):
    scan_limit: int = 20
    revoke: bool = False  # if True, remove trial


class SetTierRequest(BaseModel):
    tier: str  # starter | pro | enterprise


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_org(db: AsyncSession, org_id: str) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == uuid.UUID(org_id)))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/orgs", response_model=list[OrgSummary])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
) -> list[OrgSummary]:
    """List all organizations with basic stats."""
    rows = await db.execute(text("""
        SELECT
            o.id,
            o.clerk_org_id,
            o.name,
            o.tier,
            o.scan_count_current_period,
            o.settings,
            o.created_at,
            COUNT(DISTINCT s.id)  AS total_scans,
            COUNT(DISTINCT r.id)  AS total_releases
        FROM organizations o
        LEFT JOIN releases r ON r.org_id = o.id
        LEFT JOIN scans    s ON s.org_id = o.id
        GROUP BY o.id
        ORDER BY o.created_at DESC
    """))

    out: list[OrgSummary] = []
    for row in rows.mappings().all():
        settings_data: dict = row["settings"] or {}
        override = settings_data.get("scan_limit_override")
        from models.organization import TIER_SCAN_LIMIT, OrgTier as _OT
        tier_enum = _OT(row["tier"]) if row["tier"] in [e.value for e in _OT] else _OT.starter
        scan_limit = int(override) if override is not None else TIER_SCAN_LIMIT.get(tier_enum, 50)

        out.append(OrgSummary(
            id=str(row["id"]),
            clerk_org_id=row["clerk_org_id"],
            name=row["name"],
            tier=row["tier"],
            scan_count_current_period=row["scan_count_current_period"],
            scan_limit=scan_limit,
            is_trial=bool(settings_data.get("is_trial", False)),
            created_at=row["created_at"],
            total_scans=row["total_scans"],
            total_releases=row["total_releases"],
        ))
    return out


@router.get("/orgs/{org_id}/scans", response_model=list[OrgScanItem])
async def list_org_scans_admin(
    org_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[OrgScanItem]:
    """List all scans for a specific org (admin view)."""
    rows = await db.execute(text("""
        SELECT
            s.id, s.release_id, s.status, s.grade, s.readiness_score,
            s.critical_count, s.warning_count, s.info_count, s.created_at,
            r.title  AS release_title,
            r.artist AS release_artist
        FROM scans    s
        JOIN releases r ON r.id = s.release_id
        WHERE s.org_id = :org_id
        ORDER BY s.created_at DESC
        LIMIT 200
    """), {"org_id": org_id})

    return [
        OrgScanItem(
            id=str(row["id"]),
            release_id=str(row["release_id"]),
            release_title=row["release_title"],
            release_artist=row["release_artist"],
            status=row["status"],
            grade=row["grade"],
            readiness_score=row["readiness_score"],
            critical_count=row["critical_count"],
            warning_count=row["warning_count"],
            info_count=row["info_count"],
            created_at=row["created_at"],
        )
        for row in rows.mappings().all()
    ]


@router.patch("/orgs/{org_id}/trial")
async def set_trial(
    org_id: str,
    body: TrialGrantRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Grant or revoke trial access for an org."""
    org = await _get_org(db, org_id)
    settings_data: dict = dict(org.settings or {})

    if body.revoke:
        settings_data.pop("is_trial", None)
        settings_data.pop("scan_limit_override", None)
    else:
        settings_data["is_trial"] = True
        settings_data["scan_limit_override"] = body.scan_limit

    org.settings = settings_data
    await db.commit()
    await db.refresh(org)

    return {
        "org_id": str(org.id),
        "is_trial": bool(settings_data.get("is_trial", False)),
        "scan_limit": org.scan_limit,
    }


@router.patch("/orgs/{org_id}/tier")
async def set_tier(
    org_id: str,
    body: SetTierRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Grant full paid-tier access — clears trial flag and sets tier."""
    try:
        tier = OrgTier(body.tier)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown tier: {body.tier}")

    org = await _get_org(db, org_id)
    org.tier = tier
    # Remove trial restrictions
    settings_data = dict(org.settings or {})
    settings_data.pop("is_trial", None)
    settings_data.pop("scan_limit_override", None)
    org.settings = settings_data
    await db.commit()
    await db.refresh(org)

    return {
        "org_id": str(org.id),
        "tier": org.tier.value,
        "is_trial": False,
        "scan_limit": org.scan_limit,
    }


# ── ADMIN_SECRET routes (POST /admin/users/{org_id}/upgrade + helpers) ────────

class UpgradeRequest(BaseModel):
    tier: str = "enterprise"  # starter | pro | enterprise


@secret_router.get("/orgs-list")
async def list_orgs_secret(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all orgs with tier + scan stats. Auth: X-Admin-Secret header."""
    from models.organization import TIER_SCAN_LIMIT
    rows = await db.execute(text("""
        SELECT
            o.id, o.clerk_org_id, o.name, o.tier,
            o.scan_count_current_period, o.settings, o.created_at,
            COUNT(DISTINCT s.id) AS total_scans
        FROM organizations o
        LEFT JOIN scans s ON s.org_id = o.id
        GROUP BY o.id
        ORDER BY o.created_at DESC
    """))
    out = []
    for row in rows.mappings().all():
        settings_data: dict = row["settings"] or {}
        override = settings_data.get("scan_limit_override")
        tier_val = row["tier"]
        try:
            tier_enum = OrgTier(tier_val)
        except ValueError:
            tier_enum = OrgTier.starter
        scan_limit = int(override) if override is not None else TIER_SCAN_LIMIT.get(tier_enum, 50)
        out.append({
            "id": str(row["id"]),
            "name": row["name"],
            "tier": tier_val,
            "scan_count": row["scan_count_current_period"],
            "scan_limit": scan_limit,
            "total_scans": row["total_scans"],
            "created_at": row["created_at"].isoformat(),
        })
    return out


@secret_router.post("/users/{org_id}/upgrade")
async def upgrade_user(
    org_id: str,
    body: UpgradeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Set an org's tier and reset scan count.

    POST /admin/users/{org_id}/upgrade
    Header: X-Admin-Secret: <secret>
    Body: { "tier": "enterprise" }
    """
    try:
        tier = OrgTier(body.tier)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown tier: {body.tier!r}")

    org = await _get_org(db, org_id)
    org.tier = tier
    # Clear any trial/override flags — tier itself governs limits now
    settings_data = dict(org.settings or {})
    settings_data.pop("is_trial", None)
    settings_data.pop("scan_limit_override", None)
    # Enterprise gets a hard -1 override as belt-and-suspenders
    if tier == OrgTier.enterprise:
        settings_data["scan_limit_override"] = -1
    org.settings = settings_data
    await db.commit()
    await db.refresh(org)

    return {
        "org_id": str(org.id),
        "name": org.name,
        "tier": org.tier.value,
        "scan_limit": org.scan_limit,
        "message": f"Upgraded to {tier.value}",
    }
