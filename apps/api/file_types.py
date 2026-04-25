"""
Centralized file type configuration for SONGGATE.

Single source of truth for supported metadata formats.
All parsers, routers, and UI components reference this rather than
defining their own lists.

Binary upload types (audio, artwork) are separate concerns handled by
schemas/upload.py and UploadZone.tsx — they are not metadata formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field


@dataclass(frozen=True)
class MetadataFormat:
    display_label: str
    internal_key: str
    mime_types: tuple[str, ...]
    file_extensions: tuple[str, ...]
    input_supported: bool
    output_supported: bool
    display_order: int        # 1 = first; DDEX is always 1
    demo_supported: bool
    standard_supported: bool


# ── Formats — DDEX must always be first (display_order=1) ────────────────────

DDEX_XML = MetadataFormat(
    display_label="DDEX XML",
    internal_key="ddex_xml",
    mime_types=("application/xml", "text/xml"),
    file_extensions=(".xml",),
    input_supported=True,
    output_supported=False,
    display_order=1,
    demo_supported=True,
    standard_supported=True,
)

CSV = MetadataFormat(
    display_label="CSV",
    internal_key="csv",
    mime_types=("text/csv", "text/plain"),
    file_extensions=(".csv",),
    input_supported=True,
    output_supported=True,
    display_order=2,
    demo_supported=True,
    standard_supported=True,
)

JSON = MetadataFormat(
    display_label="JSON",
    internal_key="json",
    mime_types=("application/json",),
    file_extensions=(".json",),
    input_supported=True,
    output_supported=True,
    display_order=3,
    demo_supported=True,
    standard_supported=True,
)

BULK_REGISTRATION = MetadataFormat(
    display_label="Bulk Registration File (EAN)",
    internal_key="bulk_registration",
    mime_types=("text/plain", "text/csv", "application/pdf"),
    file_extensions=(".txt", ".csv", ".pdf"),
    input_supported=True,
    output_supported=False,
    display_order=4,
    demo_supported=True,
    standard_supported=True,
)

# Ordered list — DDEX always first
ALL_FORMATS: list[MetadataFormat] = sorted(
    [DDEX_XML, CSV, JSON, BULK_REGISTRATION],
    key=lambda f: f.display_order,
)

# Canonical UI copy — use this everywhere formats are mentioned
FORMAT_DISPLAY_STRING = (
    "Work with four supported formats: DDEX XML, Bulk Registration (EAN), CSV, and JSON."
)

# Extensions accepted in demo mode (metadata only, no audio/artwork)
DEMO_ACCEPTED_EXTENSIONS: frozenset[str] = frozenset(
    ext
    for fmt in ALL_FORMATS
    if fmt.demo_supported
    for ext in fmt.file_extensions
)


# ── Format detection ─────────────────────────────────────────────────────────

def detect_format(content: bytes, filename: str = "") -> str:
    """
    Detect metadata format from filename and/or content bytes.

    Returns one of: ``"xml"``, ``"csv"``, ``"json"``.
    Defaults to ``"xml"`` if detection is ambiguous.
    """
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".xml"):
        return "xml"

    # Content sniffing — inspect first 512 bytes
    head = content[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<ern:") or head.startswith(b"<NewRelease"):
        return "xml"
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    try:
        first_line = head.split(b"\n")[0].decode("utf-8-sig", errors="ignore")
        if "," in first_line and not first_line.strip().startswith("<"):
            return "csv"
    except Exception:
        pass

    return "xml"  # safe default
