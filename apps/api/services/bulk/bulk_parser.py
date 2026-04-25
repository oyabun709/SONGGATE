"""
Bulk Registration File Parser

Parses pipe-delimited (.txt) or CSV bulk registration files used by Luminate
and major distributors for catalog registration.

Expected columns (pipe-delimited or CSV, minimum 7):
  EAN | Artist | Title | Release Date | Imprint | Label | NARM Config
  [ISNI] [ISWC]   ← optional columns 8 and 9

Returns a list of ParsedRelease objects for downstream validation.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ParsedRelease:
    ean: str
    artist: str
    title: str
    release_date_raw: str           # raw MMDDYY string as-found
    release_date_parsed: date | None
    imprint: str | None
    label: str | None
    narm_config: str
    row_number: int                 # 1-indexed, not counting header
    isni: str | None = None         # International Standard Name Identifier
    iswc: str | None = None         # International Standard Musical Work Code


# ── Header detection ─────────────────────────────────────────────────────────

_HEADER_PATTERNS = re.compile(
    r"^(ean|barcode|upc|artist|title|release|imprint|label|narm|config|isni|iswc)",
    re.IGNORECASE,
)


def _looks_like_header(first_field: str) -> bool:
    """Return True if the first field looks like a column header, not a barcode."""
    stripped = first_field.strip()
    # A real EAN starts with digits only; a header starts with letters
    if not stripped:
        return False
    if stripped.isdigit():
        return False
    return bool(_HEADER_PATTERNS.match(stripped))


# ── Date parsing ─────────────────────────────────────────────────────────────

def _parse_mmddyy(raw: str) -> date | None:
    """
    Convert MMDDYY to a date object.
    Returns None if the string is malformed or represents an invalid date.
    """
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

_MIN_COLUMNS = 7   # EAN|Artist|Title|Date|Imprint|Label|NARM
_MAX_COLUMNS = 9   # + ISNI + ISWC


def _normalise_row(fields: list[str], row_number: int) -> ParsedRelease | None:
    """
    Convert a list of raw string fields into a ParsedRelease.
    Returns None for rows that are entirely empty (skip silently).
    Columns 8 (ISNI) and 9 (ISWC) are optional.
    """
    # Pad to minimum expected length so we don't IndexError on short rows
    while len(fields) < _MIN_COLUMNS:
        fields.append("")

    # Check if all fields are empty — skip silently
    if all(f.strip() == "" for f in fields):
        return None

    ean         = fields[0].strip()
    artist      = fields[1].strip()
    title       = fields[2].strip()
    date_raw    = fields[3].strip()
    imprint     = fields[4].strip() or None
    label       = fields[5].strip() or None
    narm_config = fields[6].strip()

    # Optional identifier columns
    isni = fields[7].strip() or None if len(fields) > 7 else None
    iswc = fields[8].strip() or None if len(fields) > 8 else None

    return ParsedRelease(
        ean=ean,
        artist=artist,
        title=title,
        release_date_raw=date_raw,
        release_date_parsed=_parse_mmddyy(date_raw),
        imprint=imprint,
        label=label,
        narm_config=narm_config,
        row_number=row_number,
        isni=isni,
        iswc=iswc,
    )


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_bulk_file(content: bytes) -> list[ParsedRelease]:
    """
    Parse a bulk registration file (pipe-delimited or CSV).

    Accepts:
      - Pipe-delimited .txt files (7–9 columns)
      - CSV files with the same columns
      - UTF-8 or UTF-8-BOM encoded files

    Column order:
      EAN | Artist | Title | Release Date | Imprint | Label | NARM [| ISNI [| ISWC]]

    Returns a list of ParsedRelease objects (header row and empty rows excluded).
    """
    text = content.decode("utf-8-sig", errors="replace")

    # Detect delimiter by counting occurrences in the first non-empty line
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []

    first_line  = lines[0]
    pipe_count  = first_line.count("|")
    comma_count = first_line.count(",")

    delimiter = "|" if pipe_count >= comma_count else ","

    # Parse with csv module (handles quoting, edge cases)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    releases: list[ParsedRelease] = []
    row_number = 0

    for i, raw_fields in enumerate(reader):
        # Skip header row
        if i == 0 and raw_fields and _looks_like_header(raw_fields[0]):
            continue

        row_number += 1
        release = _normalise_row(list(raw_fields), row_number)
        if release is not None:
            releases.append(release)

    return releases


def extract_text_from_pdf(pdf_bytes: bytes) -> bytes:
    """
    Extract text content from a PDF and return as UTF-8 bytes.
    Raises ImportError if pypdf is not installed.
    Raises ValueError if the PDF yields no extractable text.
    """
    try:
        import pypdf  # type: ignore
    except ImportError:
        raise ImportError(
            "pypdf is required for PDF bulk registration files. "
            "Install it with: pip install pypdf"
        )

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(text.splitlines())

    full_text = "\n".join(lines).strip()
    if not full_text:
        raise ValueError("PDF contains no extractable text. Is this a scanned image PDF?")

    return full_text.encode("utf-8")
