"""
Bulk Registration File Validator

Runs per-release and cross-release validation checks on a list of ParsedRelease
objects produced by bulk_parser.parse_bulk_file().

Per-release checks:
  - EAN format (13 digits, valid GS1 check digit, not all zeros)
  - Artist name (non-empty, <= 255 chars)
  - Title (non-empty, <= 255 chars)
  - Release date (valid MMDDYY, sane year range)
  - Imprint/label (both empty = warning)
  - NARM configuration code (known codes)
  - ISNI format and presence (Phase 2)
  - ISWC format and presence (Phase 2)

Cross-release checks:
  - Duplicate EAN detection
  - Artist name inconsistency across duplicate EANs
  - Title case inconsistency across duplicate EANs
  - Release date clustering (future > 6 months)
  - ISNI consistency across same artist name (Phase 2)
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from services.bulk.bulk_parser import ParsedRelease


# ── Issue dataclass ───────────────────────────────────────────────────────────

@dataclass
class BulkIssue:
    id: str
    severity: str           # "critical" | "warning" | "info"
    rule_id: str            # FK to rules.id (seeded via migration 0007)
    rule_name: str
    message: str
    fix_hint: str
    scope: str              # "per_release" | "cross_release"
    row_number: int | None  # None for cross-release issues
    affected_ean: str | None = None
    affected_rows: list[int] = field(default_factory=list)


def _issue(
    severity: str,
    rule_id: str,
    rule_name: str,
    message: str,
    fix_hint: str,
    scope: str,
    row_number: int | None = None,
    affected_ean: str | None = None,
    affected_rows: list[int] | None = None,
) -> BulkIssue:
    return BulkIssue(
        id=str(uuid.uuid4()),
        severity=severity,
        rule_id=rule_id,
        rule_name=rule_name,
        message=message,
        fix_hint=fix_hint,
        scope=scope,
        row_number=row_number,
        affected_ean=affected_ean,
        affected_rows=affected_rows or [],
    )


# ── GS1 EAN-13 check digit ────────────────────────────────────────────────────

def _gs1_check_digit(ean12: str) -> int:
    """
    Calculate the GS1 check digit for a 12-digit EAN prefix.
    Weights alternate: positions 1,3,5,7,9,11 get weight 1;
    positions 2,4,6,8,10,12 get weight 3.
    """
    total = sum(
        int(ean12[i]) * (1 if i % 2 == 0 else 3)
        for i in range(12)
    )
    return (10 - (total % 10)) % 10


def validate_ean(ean: str) -> str | None:
    """Return an error message if the EAN is invalid, or None if valid."""
    if not ean or not ean.isdigit():
        return "Invalid EAN format — must be 13 digits with valid check digit"
    if len(ean) != 13:
        return f"Invalid EAN format — must be 13 digits, got {len(ean)}"
    if ean == "0" * 13:
        return "Invalid EAN — all zeros is not a valid barcode"
    expected = _gs1_check_digit(ean[:12])
    if int(ean[12]) != expected:
        return (
            f"Invalid EAN check digit — expected {expected}, "
            f"got {ean[12]} (full EAN: {ean})"
        )
    return None


# ── ISNI validation ───────────────────────────────────────────────────────────

def validate_isni(isni: str) -> str | None:
    """
    Return an error message if the ISNI format is invalid, or None if valid.

    Rules:
    - Strip hyphens and spaces before checking
    - Must be exactly 16 digits
    - Cannot be all zeros

    Note: Full ISO 27729 check digit verification is stubbed here.
    The check digit algorithm (EAN-13 style, alternating weights 1/3
    over first 15 digits) can be wired in once confirmed against the
    ISNI International Authority registry. The sample ISNIs from the
    Luminate/Quansic pipeline pass the 16-digit format check.
    """
    clean = isni.replace("-", "").replace(" ", "")
    if not clean.isdigit() or len(clean) != 16:
        return "Invalid ISNI format — must be 16 digits (e.g. 0000-0001-2145-5467)"
    if clean == "0" * 16:
        return "Invalid ISNI — all zeros is not a valid identifier"
    return None


# ── ISWC validation ───────────────────────────────────────────────────────────

_ISWC_WITH_HYPHENS    = re.compile(r"^T-\d{9}-\d$")
_ISWC_WITHOUT_HYPHENS = re.compile(r"^T\d{10}$")


def validate_iswc(iswc: str) -> str | None:
    """
    Return an error message if the ISWC format is invalid, or None if valid.

    Accepted formats:
    - T-XXXXXXXXX-C  (with hyphens, standard notation)
    - TXXXXXXXXXX    (without hyphens, 11 chars)

    Note: Check digit validation (weighted positional sum mod 10) is stubbed.
    The algorithm can be wired in when verifying against CISAC registry data.
    """
    s = iswc.strip()
    if _ISWC_WITH_HYPHENS.match(s) or _ISWC_WITHOUT_HYPHENS.match(s):
        return None
    return "Invalid ISWC format — expected T-XXXXXXXXX-C (e.g. T-070.195.720-5)"


# ── NARM config codes ─────────────────────────────────────────────────────────

_KNOWN_NARM_CODES: dict[str, str] = {
    "00": "Album",
    "02": "Single",
    "04": "EP",
    "05": "Box Set",
    "06": "Compilation",
}


# ── Per-release validation ────────────────────────────────────────────────────

def _validate_release(release: ParsedRelease, today: date) -> list[BulkIssue]:
    issues: list[BulkIssue] = []
    row = release.row_number

    # ── EAN ──────────────────────────────────────────────────────────────────
    ean_err = validate_ean(release.ean)
    if ean_err:
        issues.append(_issue(
            severity="critical",
            rule_id="BULK_EAN_FORMAT",
            rule_name="EAN Format",
            message=ean_err,
            fix_hint=(
                "Verify the EAN against your distributor's barcode allocation. "
                "EAN-13 barcodes must pass the GS1 check digit algorithm."
            ),
            scope="per_release",
            row_number=row,
        ))

    # ── Artist name ───────────────────────────────────────────────────────────
    if not release.artist.strip():
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_ARTIST_MISSING",
            rule_name="Missing Artist Name",
            message="Missing artist name",
            fix_hint="Every release requires an artist name for DSP delivery and chart tracking.",
            scope="per_release",
            row_number=row,
        ))
    elif len(release.artist) > 255:
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_ARTIST_MISSING",
            rule_name="Artist Name Too Long",
            message=f"Artist name exceeds 255 characters ({len(release.artist)} chars)",
            fix_hint="Shorten the artist name. Use a primary artist name and add collaborators as featured artists.",
            scope="per_release",
            row_number=row,
        ))

    # ── Title ─────────────────────────────────────────────────────────────────
    if not release.title.strip():
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_TITLE_MISSING",
            rule_name="Missing Release Title",
            message="Missing release title",
            fix_hint="Every release requires a title for DSP delivery.",
            scope="per_release",
            row_number=row,
        ))
    elif len(release.title) > 255:
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_TITLE_MISSING",
            rule_name="Release Title Too Long",
            message=f"Release title exceeds 255 characters ({len(release.title)} chars)",
            fix_hint="Shorten the release title.",
            scope="per_release",
            row_number=row,
        ))

    # ── Release date ──────────────────────────────────────────────────────────
    raw_date = release.release_date_raw
    if not raw_date or len(raw_date) != 6 or not raw_date.isdigit():
        issues.append(_issue(
            severity="critical",
            rule_id="BULK_DATE_FORMAT",
            rule_name="Invalid Release Date Format",
            message=f"Invalid release date format — expected MMDDYY, got '{raw_date}'",
            fix_hint="Release dates must be in MMDDYY format, e.g. 041826 for April 18, 2026.",
            scope="per_release",
            row_number=row,
        ))
    else:
        month = int(raw_date[0:2])
        if month < 1 or month > 12:
            issues.append(_issue(
                severity="critical",
                rule_id="BULK_DATE_FORMAT",
                rule_name="Invalid Release Date",
                message=f"Invalid release date — month '{raw_date[0:2]}' is not 01–12",
                fix_hint="Release dates must be in MMDDYY format with a valid month (01–12).",
                scope="per_release",
                row_number=row,
            ))
        elif release.release_date_parsed is None:
            issues.append(_issue(
                severity="critical",
                rule_id="BULK_DATE_FORMAT",
                rule_name="Invalid Release Date",
                message=f"Invalid release date '{raw_date}' — not a real calendar date",
                fix_hint="Verify the date is a valid MMDDYY date (e.g. February cannot have day 30).",
                scope="per_release",
                row_number=row,
            ))
        else:
            parsed = release.release_date_parsed
            two_years_ago = today.replace(year=today.year - 2)
            if parsed < two_years_ago:
                issues.append(_issue(
                    severity="warning",
                    rule_id="BULK_DATE_FORMAT",
                    rule_name="Old Release Date",
                    message=(
                        f"Release date {parsed.strftime('%B %d, %Y')} appears to be more "
                        f"than 2 years in the past — verify this is correct"
                    ),
                    fix_hint=(
                        "If this is a back-catalog registration, confirm the date is intentional. "
                        "For new releases, check for a typo in the year."
                    ),
                    scope="per_release",
                    row_number=row,
                ))

    # ── Imprint + label ───────────────────────────────────────────────────────
    if not release.imprint and not release.label:
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_IMPRINT_MISSING",
            rule_name="Missing Imprint and Label",
            message="Missing imprint and label — required for rights attribution and royalty routing",
            fix_hint=(
                "Add the imprint name and parent label. These fields are required by Luminate "
                "for rights attribution and by distributors for royalty routing."
            ),
            scope="per_release",
            row_number=row,
        ))

    # ── NARM config code ──────────────────────────────────────────────────────
    if release.narm_config and release.narm_config not in _KNOWN_NARM_CODES:
        issues.append(_issue(
            severity="warning",
            rule_id="BULK_NARM_UNKNOWN",
            rule_name="Unknown NARM Configuration Code",
            message=(
                f"Unknown NARM configuration code '{release.narm_config}' — "
                f"verify against NARM standard"
            ),
            fix_hint=(
                "Known NARM codes: "
                + ", ".join(f"{k} = {v}" for k, v in _KNOWN_NARM_CODES.items())
            ),
            scope="per_release",
            row_number=row,
        ))

    # ── ISNI (Phase 2) ────────────────────────────────────────────────────────
    if release.isni:
        isni_err = validate_isni(release.isni)
        if isni_err:
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_ISNI_FORMAT",
                rule_name="Invalid ISNI",
                message=f"Invalid ISNI format for row {row}: {isni_err}",
                fix_hint=(
                    "Verify ISNI at isni.org or through "
                    "Luminate Data Enrichment ArtistMatch service."
                ),
                scope="per_release",
                row_number=row,
            ))
    else:
        issues.append(_issue(
            severity="info",
            rule_id="BULK_ISNI_MISSING",
            rule_name="Missing ISNI",
            message="ISNI not present — artist identifier missing",
            fix_hint=(
                "Add ISNI for this artist to enable accurate identifier matching in downstream "
                "systems including Luminate Data Enrichment. Look up or register at isni.org "
                "or use Luminate ArtistMatch."
            ),
            scope="per_release",
            row_number=row,
        ))

    # ── ISWC (Phase 2) ────────────────────────────────────────────────────────
    if release.iswc:
        iswc_err = validate_iswc(release.iswc)
        if iswc_err:
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_ISWC_FORMAT",
                rule_name="Invalid ISWC",
                message=f"Invalid ISWC format for row {row}: {iswc_err}",
                fix_hint=(
                    "Verify ISWC through your PRO or publisher. "
                    "ISWCs are assigned by CISAC member organizations."
                ),
                scope="per_release",
                row_number=row,
            ))
    else:
        issues.append(_issue(
            severity="info",
            rule_id="BULK_ISWC_MISSING",
            rule_name="Missing ISWC",
            message="ISWC not present — composition identifier missing",
            fix_hint=(
                "Add ISWC to enable WorksMatch linking in Luminate Data Enrichment. "
                "Register through your PRO (ASCAP, BMI, SESAC) or publisher."
            ),
            scope="per_release",
            row_number=row,
        ))

    return issues


# ── Cross-release validation ──────────────────────────────────────────────────

def _normalise_artist(artist: str) -> str:
    """Normalise artist string for comparison (lowercase, strip whitespace)."""
    return artist.strip().lower()


def _validate_cross_release(
    releases: list[ParsedRelease],
    today: date,
) -> list[BulkIssue]:
    issues: list[BulkIssue] = []

    # ── Group by EAN ─────────────────────────────────────────────────────────
    by_ean: dict[str, list[ParsedRelease]] = defaultdict(list)
    for r in releases:
        if r.ean:
            by_ean[r.ean].append(r)

    for ean, group in by_ean.items():
        if len(group) < 2:
            continue

        rows = [r.row_number for r in group]

        # Duplicate EAN — critical
        issues.append(_issue(
            severity="critical",
            rule_id="BULK_EAN_DUPLICATE",
            rule_name="Duplicate EAN",
            message=(
                f"EAN {ean} appears {len(group)} times — "
                f"rows {', '.join(str(r) for r in rows)}"
            ),
            fix_hint=(
                "Each EAN must be unique. If this is the same release with variant formats "
                "(e.g. explicit/clean), use distinct EANs per variant. "
                "If it is a duplicate entry, remove the extra rows."
            ),
            scope="cross_release",
            affected_ean=ean,
            affected_rows=rows,
        ))

        # Artist inconsistency across duplicates
        artists = [r.artist for r in group]
        unique_artists = set(_normalise_artist(a) for a in artists)
        if len(unique_artists) > 1:
            displayed = " vs ".join(f'"{a}"' for a in dict.fromkeys(artists))
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_ARTIST_INCONSISTENT",
                rule_name="Duplicate EAN — Inconsistent Artist Name",
                message=f"Duplicate EAN {ean} has inconsistent artist names: {displayed}",
                fix_hint=(
                    "Standardize artist name format across all entries for this release. "
                    "Use a consistent separator (& or ,) and consistent casing."
                ),
                scope="cross_release",
                affected_ean=ean,
                affected_rows=rows,
            ))

        # Title inconsistency across duplicates
        titles = [r.title for r in group]
        unique_titles_lower = set(t.lower() for t in titles)
        if len(unique_titles_lower) == 1 and len(set(titles)) > 1:
            displayed = " vs ".join(f'"{t}"' for t in dict.fromkeys(titles))
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_TITLE_INCONSISTENT",
                rule_name="Duplicate EAN — Title Case Inconsistency",
                message=f"Duplicate EAN {ean} has title case inconsistency: {displayed}",
                fix_hint=(
                    "Standardize title capitalization across all entries for this release. "
                    "Use your house style guide consistently."
                ),
                scope="cross_release",
                affected_ean=ean,
                affected_rows=rows,
            ))
        elif len(unique_titles_lower) > 1:
            displayed = " vs ".join(f'"{t}"' for t in dict.fromkeys(titles))
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_TITLE_INCONSISTENT",
                rule_name="Duplicate EAN — Inconsistent Title",
                message=f"Duplicate EAN {ean} has different release titles: {displayed}",
                fix_hint="Verify which title is correct and remove or correct the conflicting entry.",
                scope="cross_release",
                affected_ean=ean,
                affected_rows=rows,
            ))

    # ── Far-future release dates ──────────────────────────────────────────────
    six_months_out = today + timedelta(days=183)
    for r in releases:
        if r.release_date_parsed and r.release_date_parsed > six_months_out:
            issues.append(_issue(
                severity="info",
                rule_id="BULK_DATE_FUTURE",
                rule_name="Far-Future Release Date",
                message=(
                    f"Row {r.row_number}: \"{r.title}\" is scheduled for "
                    f"{r.release_date_parsed.strftime('%B %d, %Y')} — "
                    f"more than 6 months in advance. Confirm this is intentional."
                ),
                fix_hint=(
                    "Releases registered more than 6 months in advance may be flagged by "
                    "Luminate CONNECT for review. Confirm the date is correct before submitting."
                ),
                scope="cross_release",
                row_number=r.row_number,
                affected_ean=r.ean,
                affected_rows=[r.row_number],
            ))

    # ── ISNI cross-release consistency (Phase 2) ──────────────────────────────
    # Group by normalised artist name
    by_artist: dict[str, list[ParsedRelease]] = defaultdict(list)
    for r in releases:
        if r.artist.strip():
            by_artist[_normalise_artist(r.artist)].append(r)

    for artist_key, group in by_artist.items():
        if len(group) < 2:
            continue

        isnis = [r.isni for r in group]
        present = [i for i in isnis if i]
        absent  = [r for r in group if not r.isni]
        rows    = [r.row_number for r in group]

        if not present:
            # All missing — handled per-release as info
            continue

        if present and absent:
            # Some entries have ISNI, some don't
            issues.append(_issue(
                severity="warning",
                rule_id="BULK_ISNI_INCONSISTENT",
                rule_name="ISNI Inconsistent Across Entries",
                message=(
                    f"Artist \"{group[0].artist}\" appears without ISNI in "
                    f"{len(absent)} of {len(group)} entries"
                ),
                fix_hint=(
                    "Standardize ISNI across all entries for this artist. "
                    f"Known ISNI: {present[0]}"
                ),
                scope="cross_release",
                affected_rows=rows,
            ))

        elif len(set(i for i in present if i)) > 1:
            # Multiple different ISNIs for the same artist name
            unique_isnis = list(dict.fromkeys(i for i in present if i))
            issues.append(_issue(
                severity="critical",
                rule_id="BULK_ISNI_CONFLICTING",
                rule_name="Conflicting ISNI for Same Artist",
                message=(
                    f"Conflicting ISNIs for artist \"{group[0].artist}\": "
                    + " vs ".join(f'"{i}"' for i in unique_isnis)
                    + " — possible identity error"
                ),
                fix_hint=(
                    "Verify the correct ISNI at isni.org. "
                    "A single artist may only have one ISNI. "
                    "Standardize ISNI across all entries for this artist."
                ),
                scope="cross_release",
                affected_rows=rows,
            ))

    return issues


# ── Main entry point ──────────────────────────────────────────────────────────

def validate_bulk_file(
    releases: list[ParsedRelease],
    today: date | None = None,
) -> list[BulkIssue]:
    """
    Run all per-release and cross-release validation checks.

    Returns a flat list of BulkIssue objects.
    scope="per_release"    — issue on a specific row
    scope="cross_release"  — issue spanning multiple rows
    """
    if today is None:
        from datetime import date as _date
        today = _date.today()

    all_issues: list[BulkIssue] = []

    for release in releases:
        all_issues.extend(_validate_release(release, today))

    all_issues.extend(_validate_cross_release(releases, today))

    return all_issues
