"""
ISRC Reference File Parser

Parses pipe-delimited ISRC reference files used by Luminate for Market Share
submissions. ISRC files are submitted alongside EAN files.

Expected columns (pipe-delimited, minimum 4):
  ISRC | Artist | Title | ReleaseDate
  [LabelAbbreviation] [LabelName] [CountryCode]  ← optional cols 5–7

Returns a list of ParsedISRC objects for downstream validation.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ParsedISRC:
    isrc: str                        # raw as-found in file
    artist: str
    title: str
    release_date_raw: str            # raw MMDDYY string
    release_date_parsed: date | None
    row_number: int                  # 1-indexed, not counting header
    label_abbreviation: str | None = None
    label_name: str | None = None
    country_code: str | None = None


# ── Header detection ──────────────────────────────────────────────────────────

_HEADER_PATTERNS = re.compile(
    r"^(isrc|artist|title|release|label|country)",
    re.IGNORECASE,
)


def _looks_like_header(first_field: str) -> bool:
    stripped = first_field.strip()
    if not stripped:
        return False
    if stripped[0].isdigit():
        return False
    return bool(_HEADER_PATTERNS.match(stripped))


# ── Date parsing ──────────────────────────────────────────────────────────────

def _parse_mmddyy(raw: str) -> date | None:
    raw = raw.strip()
    if len(raw) != 6 or not raw.isdigit():
        return None
    try:
        month = int(raw[0:2])
        day   = int(raw[2:4])
        year  = 2000 + int(raw[4:6])
        return date(year, month, day)
    except ValueError:
        return None


# ── Row normaliser ────────────────────────────────────────────────────────────

_MIN_COLUMNS = 4   # ISRC|Artist|Title|ReleaseDate


def _normalise_row(fields: list[str], row_number: int) -> ParsedISRC | None:
    while len(fields) < _MIN_COLUMNS:
        fields.append("")

    if all(f.strip() == "" for f in fields):
        return None

    def _get(idx: int) -> str | None:
        if idx < len(fields):
            v = fields[idx].strip()
            return v or None
        return None

    isrc      = fields[0].strip()
    artist    = fields[1].strip()
    title     = fields[2].strip()
    date_raw  = fields[3].strip()
    label_abbr = _get(4)
    label_name = _get(5)
    country    = _get(6)

    return ParsedISRC(
        isrc=isrc,
        artist=artist,
        title=title,
        release_date_raw=date_raw,
        release_date_parsed=_parse_mmddyy(date_raw),
        row_number=row_number,
        label_abbreviation=label_abbr,
        label_name=label_name,
        country_code=country,
    )


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_isrc_file(content: bytes) -> list[ParsedISRC]:
    """
    Parse a Luminate ISRC reference file (pipe-delimited or CSV).

    Column order:
      ISRC | Artist | Title | ReleaseDate
      [LabelAbbreviation] [LabelName] [CountryCode]

    Returns a list of ParsedISRC objects (header and empty rows excluded).
    """
    text = content.decode("utf-8-sig", errors="replace")

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    first_line  = lines[0]
    pipe_count  = first_line.count("|")
    comma_count = first_line.count(",")
    delimiter   = "|" if pipe_count >= comma_count else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    records: list[ParsedISRC] = []
    row_number = 0

    for i, raw_fields in enumerate(reader):
        if i == 0 and raw_fields and _looks_like_header(raw_fields[0]):
            continue
        row_number += 1
        record = _normalise_row(list(raw_fields), row_number)
        if record is not None:
            records.append(record)

    return records
