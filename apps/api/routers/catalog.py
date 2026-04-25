"""
Catalog Explorer API

Cross-scan metadata corpus endpoints for the authenticated dashboard.
All endpoints are scoped to the authenticated org's catalog_index rows.

GET /catalog/stats           — summary counts
GET /catalog/conflicts       — EANs with conflicting data across scans
GET /catalog/artist-variants — artist names submitted in multiple formats
GET /catalog/coverage        — ISNI/ISWC identifier coverage breakdown
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/stats")
async def get_catalog_stats(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Catalog-level summary statistics for this org.

    Returns:
      total_releases   — total rows in catalog_index for this org
      unique_eans      — number of distinct EANs
      conflicted_eans  — EANs that appear with differing artist/title
      artist_variants  — artists submitted in 2+ raw name formats
      isni_coverage    — % of releases with ISNI present
      iswc_coverage    — % of releases with ISWC present
    """
    base_row = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                          AS total_releases,
                COUNT(DISTINCT ean)                                               AS unique_eans,
                COUNT(*) FILTER (WHERE isni IS NOT NULL AND isni != '')           AS with_isni,
                COUNT(*) FILTER (WHERE iswc IS NOT NULL AND iswc != '')           AS with_iswc
            FROM catalog_index
            WHERE org_id = :org_id
        """),
        {"org_id": str(org.id)},
    )
    stats = dict(base_row.mappings().one())
    total = int(stats["total_releases"] or 0)
    with_isni = int(stats["with_isni"] or 0)
    with_iswc = int(stats["with_iswc"] or 0)

    # Count EANs with conflicting artist or title across scans
    conflict_row = await db.execute(
        text("""
            SELECT COUNT(*) AS conflicted_eans
            FROM (
                SELECT ean
                FROM catalog_index
                WHERE org_id = :org_id
                GROUP BY ean
                HAVING COUNT(DISTINCT artist_normalized) > 1
                    OR COUNT(DISTINCT title_normalized) > 1
                    OR COUNT(DISTINCT isni) FILTER (WHERE isni IS NOT NULL) > 1
            ) AS conflicts
        """),
        {"org_id": str(org.id)},
    )
    conflicted_eans = int(conflict_row.scalar() or 0)

    # Count artist disambiguation cases
    variant_row = await db.execute(
        text("""
            SELECT COUNT(*) AS artist_variants
            FROM (
                SELECT artist_normalized
                FROM catalog_index
                WHERE org_id = :org_id
                  AND artist_normalized IS NOT NULL
                  AND artist_normalized != ''
                GROUP BY artist_normalized
                HAVING COUNT(DISTINCT artist) > 1
            ) AS variants
        """),
        {"org_id": str(org.id)},
    )
    artist_variants = int(variant_row.scalar() or 0)

    return {
        "total_releases": total,
        "unique_eans": int(stats["unique_eans"] or 0),
        "conflicted_eans": conflicted_eans,
        "artist_variants": artist_variants,
        "isni_coverage": round(with_isni / total * 100, 1) if total else 0.0,
        "iswc_coverage": round(with_iswc / total * 100, 1) if total else 0.0,
    }


@router.get("/conflicts")
async def get_catalog_conflicts(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page (max 100)"),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    EANs with conflicting metadata across catalog submissions, paginated.

    An EAN is "conflicted" when it appears in catalog_index with:
    - Different normalized artist names (critical)
    - Different normalized titles (warning)
    - Different ISNIs (critical)

    Returns paginated list sorted by severity (critical first), then EAN.
    """
    _CONFLICT_FILTER = """
        HAVING COUNT(DISTINCT artist_normalized) > 1
            OR COUNT(DISTINCT title_normalized) > 1
            OR (COUNT(DISTINCT isni) FILTER (WHERE isni IS NOT NULL AND isni != '')) > 1
    """

    # Total count for pagination
    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*) FROM (
                SELECT ean FROM catalog_index
                WHERE org_id = :org_id
                GROUP BY ean
                {_CONFLICT_FILTER}
            ) AS subq
        """),
        {"org_id": str(org.id)},
    )
    total = int(count_result.scalar() or 0)
    offset = (page - 1) * per_page

    rows = await db.execute(
        text(f"""
            SELECT
                ean,
                array_agg(DISTINCT artist   ORDER BY artist)  AS artist_variants,
                array_agg(DISTINCT title    ORDER BY title)   AS title_variants,
                COUNT(DISTINCT artist_normalized) > 1          AS has_artist_conflict,
                COUNT(DISTINCT title_normalized) > 1           AS has_title_conflict,
                (COUNT(DISTINCT isni) FILTER (WHERE isni IS NOT NULL AND isni != '')) > 1
                                                               AS has_isni_conflict,
                COUNT(*)                                       AS scan_count,
                MIN(first_seen)                                AS first_seen,
                MAX(last_seen)                                 AS last_seen
            FROM catalog_index
            WHERE org_id = :org_id
            GROUP BY ean
            {_CONFLICT_FILTER}
            ORDER BY has_artist_conflict DESC, ean
            LIMIT :limit OFFSET :offset
        """),
        {"org_id": str(org.id), "limit": per_page, "offset": offset},
    )

    data = []
    for row in rows.mappings().all():
        has_artist = bool(row["has_artist_conflict"])
        has_isni   = bool(row["has_isni_conflict"])
        severity   = "critical" if has_artist or has_isni else "warning"
        data.append({
            "ean":               row["ean"],
            "artist_variants":   list(row["artist_variants"] or []),
            "title_variants":    list(row["title_variants"]  or []),
            "has_artist_conflict": has_artist,
            "has_title_conflict":  bool(row["has_title_conflict"]),
            "has_isni_conflict":   has_isni,
            "scan_count":        int(row["scan_count"]),
            "first_seen":        row["first_seen"].isoformat()  if row["first_seen"]  else None,
            "last_seen":         row["last_seen"].isoformat()   if row["last_seen"]   else None,
            "severity":          severity,
        })
    return {
        "data":        data,
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": max(1, math.ceil(total / per_page)) if total else 1,
    }


@router.get("/artist-variants")
async def get_artist_variants(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(25, ge=1, le=100, description="Results per page (max 100)"),
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    Artist names that resolve to the same normalized form but appear in
    different raw formats across catalog submissions.

    Example: "RZA & Juice Crew" and "RZA, Juice Crew" both normalize to
    "rza and juice crew" — one disambiguation entry is returned.

    Returns paginated, sorted by EAN count descending (highest-impact variants first).
    """
    count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM (
                SELECT artist_normalized
                FROM catalog_index
                WHERE org_id = :org_id
                  AND artist_normalized IS NOT NULL
                  AND artist_normalized != ''
                GROUP BY artist_normalized
                HAVING COUNT(DISTINCT artist) > 1
            ) AS subq
        """),
        {"org_id": str(org.id)},
    )
    total = int(count_result.scalar() or 0)
    offset = (page - 1) * per_page

    rows = await db.execute(
        text("""
            SELECT
                artist_normalized                                               AS normalized,
                array_agg(DISTINCT artist ORDER BY artist)                     AS raw_variants,
                COUNT(DISTINCT ean)                                             AS ean_count,
                COUNT(DISTINCT isni) FILTER (WHERE isni IS NOT NULL AND isni != '')
                                                                               AS unique_isni_count,
                COUNT(*) FILTER (WHERE isni IS NOT NULL AND isni != '')        AS with_isni_count,
                COUNT(*)                                                        AS total_count
            FROM catalog_index
            WHERE org_id = :org_id
              AND artist_normalized IS NOT NULL
              AND artist_normalized != ''
            GROUP BY artist_normalized
            HAVING COUNT(DISTINCT artist) > 1
            ORDER BY COUNT(DISTINCT ean) DESC, artist_normalized
            LIMIT :limit OFFSET :offset
        """),
        {"org_id": str(org.id), "limit": per_page, "offset": offset},
    )

    data = []
    for row in rows.mappings().all():
        unique_isni = int(row["unique_isni_count"] or 0)
        with_isni   = int(row["with_isni_count"]   or 0)
        total_count = int(row["total_count"])

        if unique_isni > 1:
            isni_status = "conflicting"
        elif with_isni > 0 and with_isni < total_count:
            isni_status = "partial"
        elif with_isni == total_count and total_count > 0:
            isni_status = "present"
        else:
            isni_status = "missing"

        data.append({
            "normalized":   row["normalized"],
            "raw_variants": list(row["raw_variants"] or []),
            "ean_count":    int(row["ean_count"]),
            "isni_status":  isni_status,
        })
    return {
        "data":        data,
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": max(1, math.ceil(total / per_page)) if total else 1,
    }


@router.get("/coverage")
async def get_coverage(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """
    ISNI and ISWC identifier coverage across the org's full catalog index.

    Returns aggregate counts and percentages for use in the dashboard
    Identifier Coverage panel.
    """
    row = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                                AS total,
                COUNT(*) FILTER (WHERE isni IS NOT NULL AND isni != '')                 AS with_isni,
                COUNT(*) FILTER (WHERE iswc IS NOT NULL AND iswc != '')                 AS with_iswc,
                COUNT(*) FILTER (
                    WHERE (isni IS NOT NULL AND isni != '')
                      AND (iswc IS NOT NULL AND iswc != '')
                )                                                                        AS with_both,
                COUNT(*) FILTER (
                    WHERE (isni IS NULL OR isni = '')
                      AND (iswc IS NULL OR iswc = '')
                )                                                                        AS with_neither
            FROM catalog_index
            WHERE org_id = :org_id
        """),
        {"org_id": str(org.id)},
    )
    stats = dict(row.mappings().one())
    total     = int(stats["total"]     or 0)
    with_isni = int(stats["with_isni"] or 0)
    with_iswc = int(stats["with_iswc"] or 0)

    return {
        "total_releases": total,
        "with_isni":      with_isni,
        "with_iswc":      with_iswc,
        "with_both":      int(stats["with_both"]    or 0),
        "with_neither":   int(stats["with_neither"] or 0),
        "isni_pct":       round(with_isni / total * 100, 1) if total else 0.0,
        "iswc_pct":       round(with_iswc / total * 100, 1) if total else 0.0,
    }
