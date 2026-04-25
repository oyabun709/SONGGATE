"""
Bulk Registration File Parser

Parses pipe-delimited (.txt) or CSV bulk registration files used by Luminate
and major distributors for catalog registration.

Expected columns (pipe-delimited or CSV, minimum 7):
  EAN | Artist | Title | Release Date | Imprint | Label | NARM Config
  [LabelAbbreviation] [CountryCode] [ISNI] [ISWC]  ← optional cols 8–11

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
    label_abbreviation: str | None = None  # Short label code (1–10 chars)
    country_code: str | None = None        # ISO 3166-1 alpha-2 (e.g. US, GB)


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

_MIN_COLUMNS = 7    # EAN|Artist|Title|Date|Imprint|Label|NARM
_MAX_COLUMNS = 11   # + LabelAbbreviation + CountryCode + ISNI + ISWC


def _get(fields: list[str], idx: int) -> str | None:
    """Return stripped field at index, or None if missing/empty."""
    if idx < len(fields):
        v = fields[idx].strip()
        return v or None
    return None


def _normalise_row(fields: list[str], row_number: int) -> ParsedRelease | None:
    """
    Convert a list of raw string fields into a ParsedRelease.
    Returns None for rows that are entirely empty (skip silently).

    Column layout (minimum 7, maximum 11):
      0  EAN
      1  Artist
      2  Title
      3  Release Date (MMDDYY)
      4  Imprint
      5  Label
      6  NARM Config
      7  LabelAbbreviation  (optional)
      8  CountryCode        (optional, ISO 3166-1 alpha-2)
      9  ISNI               (optional)
      10 ISWC               (optional)

    Legacy 9-column files (no LabelAbbreviation/CountryCode) are also
    supported: if column 7 looks like an ISNI (16 digits) or ISWC (starts
    with T), it is treated as such.
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

    # Detect whether col 7 is LabelAbbreviation or legacy ISNI/ISWC
    col7 = (fields[7].strip() if len(fields) > 7 else "")
    col8 = (fields[8].strip() if len(fields) > 8 else "")

    # Legacy 9-column detection: col7 is ISNI (16 digits after stripping dashes)
    # or ISWC (starts with T followed by digits).
    _col7_clean = col7.replace("-", "").replace(" ", "")
    _is_legacy_isni = _col7_clean.isdigit() and len(_col7_clean) == 16
    _is_legacy_iswc = bool(col7 and col7.upper().startswith("T") and col7[1:].replace("-", "").isdigit())

    if _is_legacy_isni or _is_legacy_iswc:
        # Legacy 9-col layout: col7=ISNI, col8=ISWC (no label_abbr/country)
        label_abbreviation = None
        country_code       = None
        isni = col7 or None
        iswc = col8 or None
    else:
        # Extended 11-col layout
        label_abbreviation = col7 or None
        country_code       = col8 or None
        isni = _get(fields, 9)
        iswc = _get(fields, 10)

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
        label_abbreviation=label_abbreviation,
        country_code=country_code,
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


def _find_mmddyy_idx(parts: list[str]) -> int | None:
    """
    Return the index of the first part that looks like a valid MMDDYY date
    (exactly 6 digits with 01≤MM≤12 and 01≤DD≤31).
    """
    for i, p in enumerate(parts):
        p = p.strip()
        if len(p) == 6 and p.isdigit():
            mm, dd = int(p[:2]), int(p[2:4])
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                return i
    return None


def extract_text_from_pdf(pdf_bytes: bytes) -> bytes:
    """
    Extract text content from a PDF and return as pipe-delimited UTF-8 bytes.

    Strategy:
      1. Use pypdf layout-extraction mode to preserve column spacing.
      2. If the extracted text already has pipe or comma delimiters (≥3 per
         first data line), return it unchanged — the main parser handles those.
      3. Otherwise reconstruct columns for EAN-starting rows:
         a. Split the rest of the line on 2+ spaces to get candidate parts.
         b. Find the MMDDYY date field (6 digits, valid MM/DD) — use it as an
            anchor to correctly assign artist, title, and post-date columns.
         c. Emit as pipe-delimited so the main parser reads it correctly.

    Raises ImportError if pypdf is not installed.
    Raises ValueError if no extractable or parseable text is found.
    """
    try:
        import pypdf  # type: ignore
    except ImportError:
        raise ImportError(
            "pypdf is required for PDF bulk registration files. "
            "Install it with: pip install pypdf"
        )

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_lines: list[str] = []
    for page in reader.pages:
        # layout mode preserves horizontal column spacing as runs of spaces
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text = page.extract_text() or ""
        raw_lines.extend(text.splitlines())

    full_text = "\n".join(raw_lines).strip()
    if not full_text:
        raise ValueError("PDF contains no extractable text. Is this a scanned image PDF?")

    # Check whether the text already contains pipe or comma delimiters
    non_empty = [l for l in full_text.splitlines() if l.strip()]
    if non_empty:
        sample = non_empty[0]
        if sample.count("|") >= 3 or sample.count(",") >= 3:
            return full_text.encode("utf-8")

    # No delimiters — reconstruct columns for EAN-starting rows.
    _EAN_PREFIX = re.compile(r"^(\d{13})\s*(.*)")
    pipe_lines: list[str] = []

    for line in full_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        m = _EAN_PREFIX.match(stripped)
        if not m:
            # Header row or non-data line — pass through unchanged
            pipe_lines.append(stripped)
            continue

        ean  = m.group(1)
        rest = m.group(2).strip()

        # Split the remainder on 2+ consecutive spaces
        parts = re.split(r" {2,}", rest)
        parts = [p.strip() for p in parts if p.strip()]

        # Anchor on the MMDDYY date field
        date_idx = _find_mmddyy_idx(parts)

        if date_idx is not None and date_idx >= 1:
            pre_date  = parts[:date_idx]   # [artist, title?, ...]
            date_val  = parts[date_idx]
            post_date = parts[date_idx + 1:]

            if len(pre_date) == 0:
                artist, title = "", ""
            elif len(pre_date) == 1:
                # Artist and title couldn't be separated — put all in artist
                artist, title = pre_date[0], ""
            else:
                artist = pre_date[0]
                title  = " ".join(pre_date[1:])

            row = [ean, artist, title, date_val] + post_date
        else:
            # No valid MMDDYY found — fall back to position-based
            row = [ean] + parts

        pipe_lines.append("|".join(row))

    if not pipe_lines:
        raise ValueError(
            "Could not extract structured data from this PDF. "
            "Please export the bulk registration file as pipe-delimited .txt or .csv instead."
        )

    return "\n".join(pipe_lines).encode("utf-8")
