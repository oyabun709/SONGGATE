"""
ISRC Reference File Validator

Validates ParsedISRC objects from isrc_parser.parse_isrc_file().

Per-record checks:
  - ISRC format (ISO 3901: CC-XXX-YY-NNNNN, 12 chars without hyphens)
  - ISRC uniqueness within the file
  - Artist name presence
  - Title presence
  - Release date format (MMDDYY)
  - Label/country (same rules as EAN validator)

Cross-file checks (when both EAN and ISRC files provided):
  - Artist name consistency between files for the same release

Reuses BulkIssue and _issue() from bulk_validator for a consistent
issue shape across all scan types.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from services.bulk.bulk_validator import BulkIssue, _issue, _ISO_COUNTRY_CODES
from services.bulk.isrc_parser import ParsedISRC


# ── ISRC format ───────────────────────────────────────────────────────────────
# ISO 3901: CC-XXX-YY-NNNNN
#   CC    = 2-letter country code (uppercase)
#   XXX   = 3-char registrant code (letters + digits)
#   YY    = 2-digit year
#   NNNNN = 5-digit designation

_ISRC_WITH_HYPHENS    = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$")
_ISRC_WITHOUT_HYPHENS = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


def validate_isrc_format(isrc: str) -> str | None:
    """Return error message if ISRC format is invalid, None if valid."""
    s = isrc.strip().upper()
    # Accept with or without hyphens
    if _ISRC_WITH_HYPHENS.match(s) or _ISRC_WITHOUT_HYPHENS.match(s):
        return None
    # Check stripped length
    stripped = s.replace("-", "")
    if len(stripped) != 12:
        return (
            f"Invalid ISRC format — must be 12 characters without hyphens, "
            f"got {len(stripped)} ('{isrc}')"
        )
    return (
        f"Invalid ISRC format — must follow ISO 3901: CC-XXX-YY-NNNNN "
        f"(e.g. US-PR1-26-00001). Got: '{isrc}'"
    )


# ── Per-record validation ─────────────────────────────────────────────────────

def _validate_record(record: ParsedISRC, today: date) -> list[BulkIssue]:
    issues: list[BulkIssue] = []
    row = record.row_number

    # ── ISRC format ───────────────────────────────────────────────────────────
    isrc_err = validate_isrc_format(record.isrc)
    if isrc_err:
        issues.append(_issue(
            severity="critical",
            rule_id="ISRC_FORMAT",
            rule_name="Invalid ISRC Format",
            message=isrc_err,
            fix_hint=(
                "ISRCs must follow ISO 3901: CC-XXX-YY-NNNNN where CC is a 2-letter "
                "country code, XXX is the 3-char registrant code, YY is the 2-digit year, "
                "and NNNNN is a 5-digit designation. Example: US-PR1-26-00001."
            ),
            scope="per_release",
            row_number=row,
        ))

    # ── Artist ────────────────────────────────────────────────────────────────
    if not record.artist.strip():
        issues.append(_issue(
            severity="warning",
            rule_id="ISRC_ARTIST_MISSING",
            rule_name="Missing Artist Name",
            message="Missing artist name on ISRC record",
            fix_hint="Every ISRC record requires an artist name for rights attribution.",
            scope="per_release",
            row_number=row,
        ))

    # ── Title ─────────────────────────────────────────────────────────────────
    if not record.title.strip():
        issues.append(_issue(
            severity="warning",
            rule_id="ISRC_TITLE_MISSING",
            rule_name="Missing Title",
            message="Missing title on ISRC record",
            fix_hint="Every ISRC record requires a track or release title.",
            scope="per_release",
            row_number=row,
        ))

    # ── Release date ──────────────────────────────────────────────────────────
    raw_date = record.release_date_raw
    if not raw_date or len(raw_date) != 6 or not raw_date.isdigit():
        issues.append(_issue(
            severity="critical",
            rule_id="ISRC_DATE_FORMAT",
            rule_name="Invalid Release Date Format",
            message=f"Invalid release date format — expected MMDDYY, got '{raw_date}'",
            fix_hint="Release dates must be in MMDDYY format, e.g. 041826 for April 18, 2026.",
            scope="per_release",
            row_number=row,
        ))

    # ── Label abbreviation ────────────────────────────────────────────────────
    if record.label_abbreviation:
        abbr = record.label_abbreviation
        if len(abbr) < 1 or len(abbr) > 10:
            issues.append(_issue(
                severity="warning",
                rule_id="ISRC_LABEL_ABBR_INVALID",
                rule_name="Invalid Label Abbreviation",
                message=f"Label abbreviation '{abbr}' must be 1–10 characters",
                fix_hint="Use a short label code of 1–10 alphanumeric characters.",
                scope="per_release",
                row_number=row,
            ))

    # ── Country code ──────────────────────────────────────────────────────────
    if record.country_code:
        cc = record.country_code.strip().upper()
        if not re.match(r"^[A-Z]{2}$", cc):
            issues.append(_issue(
                severity="warning",
                rule_id="ISRC_COUNTRY_CODE_INVALID",
                rule_name="Invalid Country Code",
                message=f"Country code '{record.country_code}' must be a 2-letter ISO code",
                fix_hint="Use a valid ISO 3166-1 alpha-2 country code (e.g. US, GB, FR).",
                scope="per_release",
                row_number=row,
            ))
        elif cc not in _ISO_COUNTRY_CODES:
            issues.append(_issue(
                severity="warning",
                rule_id="ISRC_COUNTRY_CODE_INVALID",
                rule_name="Invalid Country Code",
                message=f"Country code '{cc}' is not a recognized ISO 3166-1 alpha-2 code",
                fix_hint="Examples: US, GB, FR, DE, JP, AU.",
                scope="per_release",
                row_number=row,
            ))
    else:
        issues.append(_issue(
            severity="warning",
            rule_id="ISRC_COUNTRY_CODE_MISSING",
            rule_name="Missing Country Code",
            message="Missing country code — required for Luminate Market Share submissions",
            fix_hint=(
                "Add 2-letter ISO country code (e.g., US for United States). "
                "Required for all Luminate Market Share claimants."
            ),
            scope="per_release",
            row_number=row,
        ))

    return issues


# ── Cross-record validation ───────────────────────────────────────────────────

def _validate_cross_record(records: list[ParsedISRC]) -> list[BulkIssue]:
    issues: list[BulkIssue] = []

    # Normalise ISRC for dedup (strip hyphens, uppercase)
    by_isrc: dict[str, list[ParsedISRC]] = defaultdict(list)
    for r in records:
        key = r.isrc.replace("-", "").upper()
        by_isrc[key].append(r)

    for isrc_key, group in by_isrc.items():
        if len(group) < 2:
            continue
        rows = [r.row_number for r in group]
        issues.append(_issue(
            severity="critical",
            rule_id="ISRC_DUPLICATE",
            rule_name="Duplicate ISRC",
            message=(
                f"ISRC {group[0].isrc} appears {len(group)} times — "
                f"rows {', '.join(str(r) for r in rows)}"
            ),
            fix_hint=(
                "Each ISRC must be unique within the file. "
                "Assign a distinct ISRC to each recording. "
                "If two rows represent the same recording, remove the duplicate."
            ),
            scope="cross_release",
            affected_ean=group[0].isrc,
            affected_rows=rows,
        ))

    return issues


# ── Cross-file validation (EAN ↔ ISRC) ───────────────────────────────────────

def validate_cross_file_consistency(
    isrc_records: list[ParsedISRC],
    ean_artists: dict[str, str],  # artist_normalized → raw artist from EAN file
) -> list[BulkIssue]:
    """
    Compare artist names between ISRC and EAN files for the same release.

    Args:
        isrc_records: Parsed ISRC file records.
        ean_artists:  Dict mapping normalized artist name → raw artist from EAN file.
    """
    issues: list[BulkIssue] = []

    def _norm(s: str) -> str:
        return s.strip().lower()

    for record in isrc_records:
        isrc_artist_norm = _norm(record.artist)
        if isrc_artist_norm and isrc_artist_norm not in ean_artists:
            # Check if a similar (but not identical) artist exists in EAN file
            for ean_norm, ean_raw in ean_artists.items():
                if isrc_artist_norm != ean_norm and (
                    isrc_artist_norm in ean_norm or ean_norm in isrc_artist_norm
                ):
                    issues.append(_issue(
                        severity="warning",
                        rule_id="CROSS_FILE_ARTIST_MISMATCH",
                        rule_name="Artist Name Mismatch Between Files",
                        message=(
                            f"Row {record.row_number}: Artist '{record.artist}' on ISRC file "
                            f"differs from '{ean_raw}' on EAN file — "
                            "standardize before submission"
                        ),
                        fix_hint=(
                            "Use the same artist name format across both EAN and ISRC "
                            "reference files. Inconsistencies cause identifier matching "
                            "failures in Luminate CONNECT."
                        ),
                        scope="cross_release",
                        row_number=record.row_number,
                    ))
                    break

    return issues


# ── Main entry point ──────────────────────────────────────────────────────────

def validate_isrc_file(
    records: list[ParsedISRC],
    today: date | None = None,
) -> list[BulkIssue]:
    """
    Run all per-record and cross-record validation checks on ISRC file data.

    Returns a flat list of BulkIssue objects.
    """
    if today is None:
        from datetime import date as _date
        today = _date.today()

    all_issues: list[BulkIssue] = []

    for record in records:
        all_issues.extend(_validate_record(record, today))

    all_issues.extend(_validate_cross_record(records))

    return all_issues
