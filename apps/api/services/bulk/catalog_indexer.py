"""
Catalog Indexer — Cross-Scan Metadata Corpus

Builds and maintains the catalog_index table: a persistent, cross-scan corpus
of all parsed releases from authenticated bulk registration scans.

Provides:
1. index_scan_releases()      — write a scan's releases into catalog_index
2. check_cross_catalog_conflicts() — query historical data for conflicts
3. normalize_artist()         — canonical artist name for comparison
4. normalize_title()          — canonical title for comparison

Corpus value: every scan enriches the database. Over time SONGGATE becomes the
authoritative source for catching catalog-level data quality problems that no
single file scan would surface — making Luminate data consumption and Quansic
identifier matching more reliable across the full catalog lifecycle.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.bulk.bulk_parser import ParsedRelease
from services.bulk.bulk_validator import BulkIssue, _issue


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_artist(artist: str) -> str:
    """
    Normalize an artist name for cross-catalog comparison.

    Rules (applied in order):
    1. NFC unicode normalization  (Beyoncé == Beyonce after NFC+lower)
    2. Lowercase + strip
    3. Collapse multiple spaces to one
    4. Replace " & " with " and "
    5. Replace ", " (comma-space between names) with " and "
    6. Remove feat./ft./featuring and everything after it
    7. Strip again

    Examples:
    "RZA & Juice Crew"           → "rza and juice crew"
    "RZA, Juice Crew"            → "rza and juice crew"
    "Beyoncé"                    → "beyonce"
    "Drake feat. Travis Scott"   → "drake"
    "The Beatles"                → "the beatles"
    """
    if not artist:
        return ""
    s = unicodedata.normalize("NFC", artist)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r",\s+", " and ", s)
    s = re.sub(r"\s+(feat\.|ft\.|featuring)\s+.*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def normalize_title(title: str) -> str:
    """
    Normalize a release title for cross-catalog comparison.

    Rules:
    1. NFC unicode normalization
    2. Lowercase + strip
    3. Collapse multiple spaces

    Examples:
    "A Tribute To Pharoah Sanders" → "a tribute to pharoah sanders"
    "A Tribute to Pharoah Sanders" → "a tribute to pharoah sanders"
    """
    if not title:
        return ""
    s = unicodedata.normalize("NFC", title)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


# ── Indexer ───────────────────────────────────────────────────────────────────

async def index_scan_releases(
    db: AsyncSession,
    scan_id: uuid.UUID,
    releases: list[ParsedRelease],
    org_id: uuid.UUID | None,
    is_demo: bool = False,
) -> None:
    """
    Write all parsed releases from a bulk scan into catalog_index.

    Called as a background task after every authenticated bulk scan completes.
    Each row records one release's metadata for cross-catalog analysis.

    Args:
        db:        An active async database session (owns its own commit).
        scan_id:   The UUID of the completed scan.
        releases:  Parsed releases from the bulk file.
        org_id:    The owning org UUID. None for demo scans.
        is_demo:   True for demo-mode scans (org_id will be None).
    """
    now = datetime.now(timezone.utc)

    for release in releases:
        artist_norm = normalize_artist(release.artist)
        title_norm = normalize_title(release.title)

        await db.execute(
            text("""
                INSERT INTO catalog_index (
                    id, ean, artist, artist_normalized,
                    title, title_normalized, release_date,
                    imprint, label, narm_config, isni, iswc,
                    scan_id, org_id, is_demo,
                    first_seen, last_seen, occurrence_count
                ) VALUES (
                    gen_random_uuid(), :ean, :artist, :artist_normalized,
                    :title, :title_normalized, :release_date,
                    :imprint, :label, :narm_config, :isni, :iswc,
                    :scan_id, :org_id, :is_demo,
                    :now, :now, 1
                )
            """),
            {
                "ean":               release.ean,
                "artist":            release.artist or None,
                "artist_normalized": artist_norm or None,
                "title":             release.title or None,
                "title_normalized":  title_norm or None,
                "release_date":      release.release_date_parsed,
                "imprint":           release.imprint,
                "label":             release.label,
                "narm_config":       release.narm_config or None,
                "isni":              release.isni,
                "iswc":              release.iswc,
                "scan_id":           str(scan_id),
                "org_id":            str(org_id) if org_id else None,
                "is_demo":           is_demo,
                "now":               now,
            },
        )

    await db.commit()


# ── Cross-catalog conflict detection ─────────────────────────────────────────

async def check_cross_catalog_conflicts(
    db: AsyncSession,
    releases: list[ParsedRelease],
    org_id: uuid.UUID,
) -> list[BulkIssue]:
    """
    Query catalog_index for conflicts between the current scan's releases
    and historical data from this org's previous scans.

    Detects:
    - CROSS_CATALOG_EAN_CONFLICT  (critical) — same EAN, different artist
    - CROSS_CATALOG_TITLE_CONFLICT (warning) — same EAN, different title
    - CROSS_CATALOG_ISNI_CONFLICT  (critical) — same EAN, conflicting ISNIs
    - CROSS_CATALOG_ARTIST_VARIANT (warning)  — artist name submitted in
      multiple formats across catalog history

    Called synchronously before scoring so conflicts affect the readiness score.
    The current scan's releases are not yet in catalog_index (indexing happens
    after the response is returned), so there is no risk of self-comparison.

    Returns a flat list of BulkIssue objects to be merged with the per-file issues.
    """
    if not releases or not org_id:
        return []

    issues: list[BulkIssue] = []
    eans = list({r.ean for r in releases if r.ean})
    if not eans:
        return []

    # ── EAN-level conflicts ───────────────────────────────────────────────────
    result = await db.execute(
        text("""
            SELECT ean, artist, artist_normalized,
                   title, title_normalized, isni, first_seen
            FROM catalog_index
            WHERE ean = ANY(:eans)
              AND org_id = :org_id
              AND is_demo = FALSE
              AND scan_id IS NOT NULL
            ORDER BY ean, first_seen ASC
        """),
        {"eans": eans, "org_id": str(org_id)},
    )
    historical = result.mappings().all()

    # Index current releases by EAN (first occurrence wins for comparison)
    current_by_ean: dict[str, ParsedRelease] = {}
    for r in releases:
        if r.ean and r.ean not in current_by_ean:
            current_by_ean[r.ean] = r

    hist_by_ean: dict[str, list[Any]] = defaultdict(list)
    for row in historical:
        hist_by_ean[row["ean"]].append(row)

    artist_conflicted: set[str] = set()
    title_conflicted: set[str] = set()
    isni_conflicted: set[str] = set()

    for ean, hist_rows in hist_by_ean.items():
        current = current_by_ean.get(ean)
        if not current:
            continue

        current_artist_norm = normalize_artist(current.artist)
        current_title_norm = normalize_title(current.title)

        for hist in hist_rows:
            first_seen_str = (
                hist["first_seen"].strftime("%Y-%m-%d")
                if hist["first_seen"]
                else "unknown date"
            )

            # Artist conflict (critical)
            if (
                ean not in artist_conflicted
                and hist["artist_normalized"]
                and current_artist_norm
                and hist["artist_normalized"] != current_artist_norm
            ):
                artist_conflicted.add(ean)
                issues.append(_issue(
                    severity="critical",
                    rule_id="CROSS_CATALOG_EAN_CONFLICT",
                    rule_name="Cross-Catalog EAN Conflict — Artist",
                    message=(
                        f"EAN {ean} was previously submitted with a different artist name. "
                        f"Previous: \"{hist['artist']}\" ({first_seen_str}). "
                        f"Current: \"{current.artist}\". "
                        f"This conflict will cause identifier matching failures in downstream systems."
                    ),
                    fix_hint=(
                        "Standardize release data across all submissions. "
                        "Contact your distributor to reconcile historical records. "
                        "Use a consistent artist name format (& vs , vs and)."
                    ),
                    scope="per_release",
                    row_number=current.row_number,
                    affected_ean=ean,
                ))

            # Title conflict (warning)
            if (
                ean not in title_conflicted
                and hist["title_normalized"]
                and current_title_norm
                and hist["title_normalized"] != current_title_norm
            ):
                title_conflicted.add(ean)
                issues.append(_issue(
                    severity="warning",
                    rule_id="CROSS_CATALOG_TITLE_CONFLICT",
                    rule_name="Cross-Catalog EAN Conflict — Title",
                    message=(
                        f"EAN {ean} was previously submitted with a different title. "
                        f"Previous: \"{hist['title']}\" ({first_seen_str}). "
                        f"Current: \"{current.title}\"."
                    ),
                    fix_hint=(
                        "Standardize title capitalization across all submissions. "
                        "Contact your distributor to reconcile historical records."
                    ),
                    scope="per_release",
                    row_number=current.row_number,
                    affected_ean=ean,
                ))

            # ISNI conflict (critical)
            if (
                ean not in isni_conflicted
                and hist["isni"]
                and current.isni
                and hist["isni"] != current.isni
            ):
                isni_conflicted.add(ean)
                issues.append(_issue(
                    severity="critical",
                    rule_id="CROSS_CATALOG_ISNI_CONFLICT",
                    rule_name="Cross-Catalog ISNI Conflict",
                    message=(
                        f"EAN {ean} has conflicting ISNIs across catalog submissions. "
                        f"Previous: \"{hist['isni']}\" ({first_seen_str}). "
                        f"Current: \"{current.isni}\". "
                        f"Verify the correct ISNI at isni.org."
                    ),
                    fix_hint=(
                        "A single artist may only have one ISNI. "
                        "Standardize ISNI across all submissions. "
                        "Verify the correct identifier at isni.org."
                    ),
                    scope="per_release",
                    row_number=current.row_number,
                    affected_ean=ean,
                ))

    # ── Artist name disambiguation ─────────────────────────────────────────────
    # Detect artist names submitted in multiple raw formats by this org
    artist_norms = list({normalize_artist(r.artist) for r in releases if r.artist.strip()})
    if artist_norms:
        variant_result = await db.execute(
            text("""
                SELECT artist_normalized,
                       array_agg(DISTINCT artist ORDER BY artist) AS raw_variants
                FROM catalog_index
                WHERE artist_normalized = ANY(:norms)
                  AND org_id = :org_id
                  AND is_demo = FALSE
                  AND scan_id IS NOT NULL
                GROUP BY artist_normalized
                HAVING count(DISTINCT artist) > 1
            """),
            {"norms": artist_norms, "org_id": str(org_id)},
        )
        variants = variant_result.mappings().all()

        # Map current releases by normalized artist (first occurrence)
        current_by_artist_norm: dict[str, ParsedRelease] = {}
        for r in releases:
            norm = normalize_artist(r.artist)
            if norm and norm not in current_by_artist_norm:
                current_by_artist_norm[norm] = r

        seen_norms: set[str] = set()
        for row in variants:
            norm = row["artist_normalized"]
            if norm in seen_norms:
                continue
            seen_norms.add(norm)

            current_r = current_by_artist_norm.get(norm)
            if not current_r:
                continue

            raw_variants: list[str] = list(row["raw_variants"] or [])
            # Include current submission's raw name if not already present
            if current_r.artist not in raw_variants:
                raw_variants = [current_r.artist] + raw_variants
            all_variants = list(dict.fromkeys(raw_variants))
            if len(all_variants) < 2:
                continue

            variant_str = " | ".join(f'"{v}"' for v in all_variants[:4])
            issues.append(_issue(
                severity="warning",
                rule_id="CROSS_CATALOG_ARTIST_VARIANT",
                rule_name="Artist Name Disambiguation",
                message=(
                    f"Artist \"{current_r.artist}\" (normalized: \"{norm}\") has been submitted "
                    f"in multiple name formats across catalog history: {variant_str}. "
                    f"Standardize to one format to enable consistent ISNI matching."
                ),
                fix_hint=(
                    "Use a single canonical artist name format across all submissions. "
                    "Inconsistent artist names (& vs , vs and) reduce ISNI match rates "
                    "in Luminate Data Enrichment and Quansic ArtistMatch."
                ),
                scope="cross_release",
                row_number=current_r.row_number,
                affected_ean=current_r.ean,
            ))

    return issues


# ── Weekly submission tracking ────────────────────────────────────────────────

async def record_weekly_submission(
    db: AsyncSession,
    org_id: str,
    release_count: int,
    critical_count: int,
    warning_count: int,
    week_date: date | None = None,
) -> None:
    """
    Upsert a weekly_submissions row for the ISO week containing `week_date`
    (defaults to today).

    On conflict (same org + ISO week), increments the counters rather than
    overwriting, so multiple scans in the same week accumulate correctly.
    """
    target = week_date or date.today()
    # Monday of the ISO week
    iso_cal = target.isocalendar()
    iso_year = iso_cal[0]
    iso_week = iso_cal[1]
    week_start = target - __import__("datetime").timedelta(days=target.weekday())
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        text("""
            INSERT INTO weekly_submissions
                (id, org_id, week_start, iso_year, iso_week,
                 release_count, scan_count, critical_count, warning_count,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :org_id, :week_start, :iso_year, :iso_week,
                 :release_count, 1, :critical_count, :warning_count,
                 :now, :now)
            ON CONFLICT (org_id, iso_year, iso_week)
            DO UPDATE SET
                release_count  = weekly_submissions.release_count  + EXCLUDED.release_count,
                scan_count     = weekly_submissions.scan_count     + 1,
                critical_count = weekly_submissions.critical_count + EXCLUDED.critical_count,
                warning_count  = weekly_submissions.warning_count  + EXCLUDED.warning_count,
                updated_at     = EXCLUDED.updated_at
        """),
        {
            "org_id":         org_id,
            "week_start":     week_start.isoformat(),
            "iso_year":       iso_year,
            "iso_week":       iso_week,
            "release_count":  release_count,
            "critical_count": critical_count,
            "warning_count":  warning_count,
            "now":            now,
        },
    )
    await db.commit()
