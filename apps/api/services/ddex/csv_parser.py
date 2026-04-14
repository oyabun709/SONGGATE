"""
CSV ingestion parser for DDEX-lite / flat metadata sheets.

Expected CSV schema (see docs/csv_template.csv for full column list):

  Required columns:
    release_title, artist_name, upc, release_date, label_name,
    isrc, track_title, track_number, duration

  Optional columns:
    release_type, genre, parental_warning, c_line, p_line,
    territory, commercial_model, use_type, start_date, end_date,
    composer, lyricist, producer, mix_engineer,
    explicit, language, track_version, resource_reference

The parser returns a ``CSVParseResult`` which bundles the parsed metadata
and any validation findings.  It does NOT write to the database.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .validator import DDEXFinding, _ISRC_RE, _UPC_RE


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CSVParseResult:
    """Result of parsing a metadata CSV."""
    releases: list[dict[str, Any]] = field(default_factory=list)
    findings: list[DDEXFinding] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(f.severity in ("critical", "error") for f in self.findings)


# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "release_title",
    "artist_name",
    "upc",
    "release_date",
    "label_name",
    "isrc",
    "track_title",
    "track_number",
    "duration",
}

OPTIONAL_COLUMNS = {
    "release_type",
    "genre",
    "parental_warning",
    "c_line",
    "p_line",
    "territory",
    "commercial_model",
    "use_type",
    "start_date",
    "end_date",
    "composer",
    "lyricist",
    "producer",
    "mix_engineer",
    "explicit",
    "language",
    "track_version",
    "resource_reference",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DURATION_RE = re.compile(r"^\d{1,3}:\d{2}$")  # MM:SS or HHH:SS


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class CSVParser:
    """Parse a DDEX-lite metadata CSV file."""

    def parse(self, content: bytes) -> CSVParseResult:
        """
        Parse CSV bytes and return metadata + findings.

        Args:
            content: Raw CSV bytes (UTF-8 with optional BOM).

        Returns:
            CSVParseResult with releases list and validation findings.
        """
        result = CSVParseResult()

        # Decode — strip BOM if present
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            result.findings.append(
                DDEXFinding(
                    rule_id="csv.encoding",
                    severity="critical",
                    message="CSV file is not valid UTF-8.",
                    fix_hint="Save the file as UTF-8 (with or without BOM).",
                )
            )
            return result

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            result.findings.append(
                DDEXFinding(
                    rule_id="csv.empty",
                    severity="critical",
                    message="CSV file is empty or has no header row.",
                )
            )
            return result

        # Normalise column names (strip whitespace, lowercase)
        normalised_fields = [f.strip().lower() for f in reader.fieldnames]
        missing_required = REQUIRED_COLUMNS - set(normalised_fields)
        if missing_required:
            result.findings.append(
                DDEXFinding(
                    rule_id="csv.missing_columns",
                    severity="critical",
                    message=f"CSV is missing required columns: {', '.join(sorted(missing_required))}.",
                    fix_hint="See docs/csv_template.csv for the expected column list.",
                )
            )
            return result

        # Group rows by UPC (one release = one UPC, multiple tracks)
        releases_by_upc: dict[str, dict[str, Any]] = {}

        for row_num, raw_row in enumerate(reader, start=2):
            # Re-key with normalised field names
            row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items() if k}

            upc = row.get("upc", "").strip()
            if not upc:
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.missing_upc",
                        severity="error",
                        message=f"Row {row_num}: missing UPC.",
                        line=row_num,
                        fix_hint="Every row must have a UPC.",
                    )
                )
                continue

            # Validate UPC
            if not _UPC_RE.match(upc):
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.upc_format",
                        severity="error",
                        message=f"Row {row_num}: invalid UPC '{upc}' — must be 12 or 13 digits.",
                        line=row_num,
                        actual_value=upc,
                        fix_hint="UPC-A is 12 digits; EAN-13 is 13 digits.",
                    )
                )

            # Validate ISRC
            isrc = row.get("isrc", "")
            if isrc and not _ISRC_RE.match(isrc):
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.isrc_format",
                        severity="error",
                        message=f"Row {row_num}: invalid ISRC '{isrc}'.",
                        line=row_num,
                        actual_value=isrc,
                        fix_hint="ISRC must match CC-XXX-YY-NNNNN.",
                    )
                )

            # Validate release_date
            release_date = row.get("release_date", "")
            if release_date and not _DATE_RE.match(release_date):
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.date_format",
                        severity="error",
                        message=f"Row {row_num}: release_date '{release_date}' must be YYYY-MM-DD.",
                        line=row_num,
                        actual_value=release_date,
                    )
                )

            # Validate track_number
            track_number_raw = row.get("track_number", "")
            try:
                track_number = int(track_number_raw) if track_number_raw else None
            except ValueError:
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.track_number",
                        severity="error",
                        message=f"Row {row_num}: track_number '{track_number_raw}' must be an integer.",
                        line=row_num,
                        actual_value=track_number_raw,
                    )
                )
                track_number = None

            # Validate duration (MM:SS)
            duration_raw = row.get("duration", "")
            duration_ms: int | None = None
            if duration_raw:
                if _DURATION_RE.match(duration_raw):
                    parts = duration_raw.split(":")
                    duration_ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
                else:
                    result.findings.append(
                        DDEXFinding(
                            rule_id="csv.duration_format",
                            severity="warning",
                            message=f"Row {row_num}: duration '{duration_raw}' should be MM:SS.",
                            line=row_num,
                            actual_value=duration_raw,
                        )
                    )

            # Accumulate release
            if upc not in releases_by_upc:
                releases_by_upc[upc] = {
                    "upc": upc,
                    "title": row.get("release_title", ""),
                    "artist": row.get("artist_name", ""),
                    "label": row.get("label_name", ""),
                    "release_date": release_date,
                    "release_type": row.get("release_type", "") or "Album",
                    "genre": row.get("genre"),
                    "parental_warning": row.get("parental_warning"),
                    "c_line": row.get("c_line"),
                    "p_line": row.get("p_line"),
                    "territory": row.get("territory") or "Worldwide",
                    "commercial_model": row.get("commercial_model"),
                    "use_type": row.get("use_type"),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                    "tracks": [],
                }

            track: dict[str, Any] = {
                "isrc": isrc,
                "title": row.get("track_title", ""),
                "track_number": track_number,
                "duration_ms": duration_ms,
                "composer": row.get("composer"),
                "lyricist": row.get("lyricist"),
                "producer": row.get("producer"),
                "mix_engineer": row.get("mix_engineer"),
                "explicit": (row.get("explicit", "false").lower() in ("true", "yes", "1")),
                "language": row.get("language"),
                "track_version": row.get("track_version"),
                "resource_reference": row.get("resource_reference"),
            }
            releases_by_upc[upc]["tracks"].append(
                {k: v for k, v in track.items() if v not in (None, "", False) or k == "explicit"}
            )

        result.releases = list(releases_by_upc.values())

        # Post-parse checks
        for rel in result.releases:
            if not rel.get("title"):
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.missing_release_title",
                        severity="error",
                        message=f"Release with UPC {rel['upc']} has no release_title.",
                        fix_hint="Every release must have a release_title.",
                    )
                )
            if not rel.get("tracks"):
                result.findings.append(
                    DDEXFinding(
                        rule_id="csv.no_tracks",
                        severity="error",
                        message=f"Release with UPC {rel['upc']} has no tracks.",
                        fix_hint="Each release must have at least one track row.",
                    )
                )

        return result
