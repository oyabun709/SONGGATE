"""
DDEX XML validation and metadata extraction.

Validation pipeline:
  1. lxml well-formedness check (always local, instant)
  2. Structural heuristics — required top-level elements, namespace,
     ISRC / UPC format checks (always local)
  3. Remote schema + Schematron validation via ddex-workbench SDK
     (only when DDEX_WORKBENCH_API_KEY env-var is set)

DDEXParser.extract_metadata() is fully local — it never calls the
remote API and works offline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from lxml import etree


# ---------------------------------------------------------------------------
# Internal result type
# ---------------------------------------------------------------------------

@dataclass
class DDEXFinding:
    """A single validation finding (error, warning, or info)."""
    rule_id: str
    severity: str                   # "critical" | "error" | "warning" | "info"
    message: str
    field_path: Optional[str] = None   # XPath or element name
    actual_value: Optional[str] = None
    fix_hint: Optional[str] = None
    line: int = 0
    column: int = 0


# ---------------------------------------------------------------------------
# Namespace / version constants
# ---------------------------------------------------------------------------

_ERN_NS = {
    "ERN43": "http://ddex.net/xml/ern/43",
    "ERN42": "http://ddex.net/xml/ern/42",
    "ERN382": "http://ddex.net/xml/ern/382",
}

_VERSION_ALIASES: dict[str, str] = {
    "ERN43": "ERN43",
    "4.3": "ERN43",
    "ern43": "ERN43",
    "ERN42": "ERN42",
    "4.2": "ERN42",
    "ern42": "ERN42",
    "ERN382": "ERN382",
    "3.8.2": "ERN382",
    "ern382": "ERN382",
}

# Fields that MUST exist in a valid NewReleaseMessage
_REQUIRED_ELEMENTS = {
    "ERN43": [
        "MessageHeader",
        "ResourceList",
        "ReleaseList",
        "DealList",
    ],
    "ERN42": [
        "MessageHeader",
        "ResourceList",
        "ReleaseList",
        "DealList",
    ],
    "ERN382": [
        "MessageHeader",
        "ResourceList",
        "ReleaseList",
        "DealList",
    ],
}

_ISRC_RE = re.compile(r"^[A-Z]{2}-?[A-Z0-9]{3}-?\d{2}-?\d{5}$")
_UPC_RE = re.compile(r"^\d{12,13}$")
_GRid_RE = re.compile(r"^A1-[A-Z0-9]{5}-[A-Z0-9]{10}-[A-Z0-9]$")


# ---------------------------------------------------------------------------
# DDEXValidator
# ---------------------------------------------------------------------------

class DDEXValidator:
    """
    Validate DDEX XML content.

    Usage::

        validator = DDEXValidator()
        findings = validator.validate(xml_bytes, version="ERN43")
        # Returns [] on a clean document.
    """

    def __init__(self) -> None:
        self._api_key: str | None = os.getenv("DDEX_WORKBENCH_API_KEY")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        content: bytes,
        version: str = "ERN43",
    ) -> list[DDEXFinding]:
        """
        Validate DDEX XML.

        Args:
            content: Raw XML bytes.
            version: ERN version string — "ERN43" / "4.3" / "ERN42" / "4.2" /
                     "ERN382" / "3.8.2" (aliases accepted).

        Returns:
            List of DDEXFinding objects; empty list means valid.
        """
        norm_version = _VERSION_ALIASES.get(version, "ERN43")
        findings: list[DDEXFinding] = []

        # Step 1 — well-formedness
        root, parse_findings = _parse_xml(content)
        findings.extend(parse_findings)
        if root is None:
            return findings  # Cannot continue without a tree

        # Step 2 — local structural checks
        findings.extend(_check_namespace(root, norm_version))
        findings.extend(_check_required_elements(root, norm_version))
        findings.extend(_check_isrc_format(root, norm_version))
        findings.extend(_check_upc_format(root, norm_version))
        findings.extend(_check_message_header(root, norm_version))

        # Step 3 — remote schema/Schematron (optional)
        if self._api_key:
            findings.extend(self._remote_validate(content, norm_version))

        return findings

    # ------------------------------------------------------------------
    # Remote validation (ddex-workbench SDK)
    # ------------------------------------------------------------------

    def _remote_validate(
        self,
        content: bytes,
        norm_version: str,
    ) -> list[DDEXFinding]:
        """Call the ddex-workbench remote API. Returns [] on any network error."""
        try:
            import sys
            import os as _os

            sdk_path = _os.path.join(
                _os.path.dirname(__file__),
                "../../../../packages/ddex-engine/packages/python-sdk",
            )
            if sdk_path not in sys.path:
                sys.path.insert(0, sdk_path)

            from ddex_workbench.client import DDEXClient  # type: ignore

            sdk_version_map = {
                "ERN43": "4.3",
                "ERN42": "4.2",
                "ERN382": "3.8.2",
            }
            api_version = sdk_version_map[norm_version]

            with DDEXClient(api_key=self._api_key) as client:
                result = client.validate(content.decode("utf-8", errors="replace"), api_version)

            findings: list[DDEXFinding] = []
            for err in result.errors:
                findings.append(
                    DDEXFinding(
                        rule_id=err.rule or "ddex.remote.schema",
                        severity="error" if err.severity == "error" else "warning",
                        message=err.message,
                        field_path=err.xpath,
                        fix_hint=err.suggestion,
                        line=err.line,
                        column=err.column,
                    )
                )
            for warn in result.warnings:
                findings.append(
                    DDEXFinding(
                        rule_id=warn.rule or "ddex.remote.schematron",
                        severity="warning",
                        message=warn.message,
                        field_path=warn.context,
                        line=warn.line,
                        column=warn.column,
                    )
                )
            return findings

        except Exception:
            # Remote validation is best-effort; never block pipeline
            return []


# ---------------------------------------------------------------------------
# DDEXParser  — local metadata extraction
# ---------------------------------------------------------------------------

class DDEXParser:
    """
    Extract release metadata from DDEX ERN XML without any remote calls.

    Works with ERN 3.8.2, 4.2, and 4.3.
    """

    def extract_metadata(self, content: bytes) -> dict[str, Any]:
        """
        Parse DDEX XML and return a flat metadata dict.

        Returns an empty dict (plus an ``_error`` key) if parsing fails.
        """
        root, _ = _parse_xml(content)
        if root is None:
            return {"_error": "XML parse failed"}

        ns = _detect_namespace(root)
        prefix = f"{{{ns}}}" if ns else ""

        meta: dict[str, Any] = {
            "version": _detect_ern_version(root),
            "profile": _detect_profile(root, prefix),
        }

        # MessageHeader
        header = root.find(f"{prefix}MessageHeader")
        if header is not None:
            meta["sender_party_id"] = _text(header, f"{prefix}SentOnBehalfOf/{prefix}PartyId")
            meta["sender_name"] = _text(header, f"{prefix}SentOnBehalfOf/{prefix}PartyName/{prefix}FullName")
            if not meta["sender_name"]:
                meta["sender_name"] = _text(header, f"{prefix}MessageSender/{prefix}PartyName/{prefix}FullName")
            meta["message_id"] = _text(header, f"{prefix}MessageId")
            meta["message_created"] = _text(header, f"{prefix}MessageCreatedDateTime")

        # ReleaseList — grab the primary release
        release_list = root.find(f"{prefix}ReleaseList")
        if release_list is not None:
            # Primary release is typically first, or the one with IsMainRelease=true
            releases = release_list.findall(f"{prefix}Release")
            primary = None
            for rel in releases:
                is_main = rel.findtext(f"{prefix}IsMainRelease") or ""
                if is_main.lower() == "true":
                    primary = rel
                    break
            if primary is None and releases:
                primary = releases[0]

            if primary is not None:
                meta.update(_extract_release_fields(primary, prefix))

        # ResourceList — collect tracks / sound recordings
        resource_list = root.find(f"{prefix}ResourceList")
        if resource_list is not None:
            meta["tracks"] = _extract_tracks(resource_list, prefix)

        # DealList
        deal_list = root.find(f"{prefix}DealList")
        if deal_list is not None:
            meta["deals"] = _extract_deals(deal_list, prefix)

        return meta


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _parse_xml(content: bytes) -> tuple[etree._Element | None, list[DDEXFinding]]:
    """Parse XML bytes; return (root, findings). root=None if malformed."""
    findings: list[DDEXFinding] = []
    try:
        parser = etree.XMLParser(recover=False, resolve_entities=False)
        root = etree.fromstring(content, parser)
        return root, findings
    except etree.XMLSyntaxError as exc:
        findings.append(
            DDEXFinding(
                rule_id="ddex.xml.wellformed",
                severity="critical",
                message=f"XML is not well-formed: {exc}",
                fix_hint="Ensure the file is valid UTF-8 XML with balanced tags.",
                line=exc.lineno or 0,
                column=exc.offset or 0,
            )
        )
        return None, findings


def _detect_namespace(root: etree._Element) -> str:
    """Return the namespace URI declared on the root element, or empty string."""
    if root.tag.startswith("{"):
        return root.tag[1:].split("}")[0]
    return ""


def _detect_ern_version(root: etree._Element) -> str:
    ns = _detect_namespace(root)
    for ver, uri in _ERN_NS.items():
        if uri == ns:
            return ver
    return "unknown"


def _detect_profile(root: etree._Element, prefix: str) -> str | None:
    release_list = root.find(f"{prefix}ReleaseList")
    if release_list is None:
        return None
    for release in release_list.findall(f"{prefix}Release"):
        rtype = release.findtext(f"{prefix}ReleaseType")
        if rtype:
            return rtype
    return None


# ---------------------------------------------------------------------------
# Local structural checkers
# ---------------------------------------------------------------------------

def _check_namespace(root: etree._Element, norm_version: str) -> list[DDEXFinding]:
    findings: list[DDEXFinding] = []
    expected_ns = _ERN_NS.get(norm_version, "")
    actual_ns = _detect_namespace(root)

    if not actual_ns:
        findings.append(
            DDEXFinding(
                rule_id="ddex.xml.namespace",
                severity="error",
                message="Root element has no XML namespace — expected a DDEX ERN namespace.",
                fix_hint=f"Add xmlns=\"{expected_ns}\" to the root element.",
            )
        )
    elif expected_ns and actual_ns != expected_ns:
        findings.append(
            DDEXFinding(
                rule_id="ddex.xml.namespace_mismatch",
                severity="error",
                message=f"Namespace mismatch: got '{actual_ns}', expected '{expected_ns}'.",
                actual_value=actual_ns,
                fix_hint=f"Set the root namespace to '{expected_ns}' for {norm_version}.",
            )
        )
    return findings


def _check_required_elements(root: etree._Element, norm_version: str) -> list[DDEXFinding]:
    findings: list[DDEXFinding] = []
    ns = _detect_namespace(root)
    prefix = f"{{{ns}}}" if ns else ""

    for el_name in _REQUIRED_ELEMENTS.get(norm_version, []):
        if root.find(f"{prefix}{el_name}") is None:
            findings.append(
                DDEXFinding(
                    rule_id=f"ddex.structure.missing_{el_name.lower()}",
                    severity="critical",
                    message=f"Required element <{el_name}> is missing from NewReleaseMessage.",
                    fix_hint=f"Add a <{el_name}> block to the message.",
                )
            )
    return findings


def _check_isrc_format(root: etree._Element, norm_version: str) -> list[DDEXFinding]:
    findings: list[DDEXFinding] = []
    ns = _detect_namespace(root)
    prefix = f"{{{ns}}}" if ns else ""

    for el in root.iter(f"{prefix}ISRC"):
        val = (el.text or "").strip()
        if val and not _ISRC_RE.match(val):
            findings.append(
                DDEXFinding(
                    rule_id="ddex.metadata.isrc_format",
                    severity="error",
                    message=f"Invalid ISRC format: '{val}'",
                    field_path=root.getpath(el) if hasattr(root, "getpath") else "ISRC",
                    actual_value=val,
                    fix_hint="ISRC must follow the pattern CC-XXX-YY-NNNNN (e.g. GB-ABC-24-00001).",
                )
            )
    return findings


def _check_upc_format(root: etree._Element, norm_version: str) -> list[DDEXFinding]:
    findings: list[DDEXFinding] = []
    ns = _detect_namespace(root)
    prefix = f"{{{ns}}}" if ns else ""

    for el in root.iter(f"{prefix}UPC"):
        val = (el.text or "").strip()
        if val and not _UPC_RE.match(val):
            findings.append(
                DDEXFinding(
                    rule_id="ddex.metadata.upc_format",
                    severity="error",
                    message=f"Invalid UPC/EAN format: '{val}' — must be 12 or 13 digits.",
                    field_path="UPC",
                    actual_value=val,
                    fix_hint="UPC must be a 12-digit (UPC-A) or 13-digit (EAN-13) numeric string.",
                )
            )
    return findings


def _check_message_header(root: etree._Element, norm_version: str) -> list[DDEXFinding]:
    """Validate required MessageHeader sub-elements."""
    findings: list[DDEXFinding] = []
    ns = _detect_namespace(root)
    prefix = f"{{{ns}}}" if ns else ""

    header = root.find(f"{prefix}MessageHeader")
    if header is None:
        return findings  # already caught by _check_required_elements

    required_header_fields = ["MessageId", "MessageSender", "MessageRecipient", "MessageCreatedDateTime"]
    for field_name in required_header_fields:
        if header.find(f"{prefix}{field_name}") is None:
            findings.append(
                DDEXFinding(
                    rule_id=f"ddex.header.missing_{field_name.lower()}",
                    severity="error",
                    message=f"MessageHeader is missing required sub-element <{field_name}>.",
                    field_path=f"MessageHeader/{field_name}",
                    fix_hint=f"Add <{field_name}> inside <MessageHeader>.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------

def _text(element: etree._Element, path: str) -> str | None:
    """Find a sub-element by path and return its stripped text, or None."""
    el = element.find(path)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _extract_release_fields(release: etree._Element, prefix: str) -> dict[str, Any]:
    data: dict[str, Any] = {}

    # Release reference
    ref = _text(release, f"{prefix}ReleaseReference")
    if ref:
        data["release_reference"] = ref

    # GRid
    grid = _text(release, f"{prefix}ReleaseId/{prefix}GRid")
    if grid:
        data["grid"] = grid

    # ICPN (UPC/EAN for album)
    icpn = _text(release, f"{prefix}ReleaseId/{prefix}ICPN")
    if icpn:
        data["upc"] = icpn

    # Title
    title = _text(release, f"{prefix}ReferenceTitle/{prefix}TitleText")
    if not title:
        title = _text(release, f"{prefix}Title/{prefix}TitleText")
    if title:
        data["title"] = title

    # Artist
    artist_el = release.find(f"{prefix}DisplayArtistName")
    if artist_el is None:
        # Fallback: first DisplayArtist
        for da in release.iter(f"{prefix}DisplayArtist"):
            artist_el = da.find(f"{prefix}PartyName/{prefix}FullName")
            break
    data["artist"] = artist_el.text.strip() if artist_el is not None and artist_el.text else None

    # Release date
    release_date = _text(release, f"{prefix}ReleaseDate")
    if release_date:
        data["release_date"] = release_date

    # Release type
    data["release_type"] = _text(release, f"{prefix}ReleaseType")

    # Label
    data["label"] = _text(release, f"{prefix}LabelName")

    # CLine / PLine
    data["c_line"] = _text(release, f"{prefix}CLineWithYear/{prefix}CLine") or _text(release, f"{prefix}CLine")
    data["p_line"] = _text(release, f"{prefix}PLineWithYear/{prefix}PLine") or _text(release, f"{prefix}PLine")

    # Genre
    genre_el = release.find(f"{prefix}Genre/{prefix}GenreText")
    if genre_el is None:
        genre_el = release.find(f"{prefix}MainGenre/{prefix}GenreText")
    data["genre"] = genre_el.text.strip() if genre_el is not None and genre_el.text else None

    # Parental warning
    data["parental_warning"] = _text(release, f"{prefix}ParentalWarningType")

    return {k: v for k, v in data.items() if v is not None}


def _extract_tracks(resource_list: etree._Element, prefix: str) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []

    for sr in resource_list.iter(f"{prefix}SoundRecording"):
        track: dict[str, Any] = {}

        isrc = _text(sr, f"{prefix}SoundRecordingId/{prefix}ISRC")
        if isrc:
            track["isrc"] = isrc

        title = _text(sr, f"{prefix}ReferenceTitle/{prefix}TitleText")
        if not title:
            title = _text(sr, f"{prefix}Title/{prefix}TitleText")
        if title:
            track["title"] = title

        # Duration (ISO 8601 — PT3M45S)
        duration = _text(sr, f"{prefix}Duration")
        if duration:
            track["duration_iso"] = duration
            track["duration_ms"] = _iso8601_to_ms(duration)

        # Artist
        for da in sr.iter(f"{prefix}DisplayArtist"):
            name = _text(da, f"{prefix}PartyName/{prefix}FullName")
            if name:
                track["artist"] = name
            break

        # Sequence number
        seq = _text(sr, f"{prefix}SequenceNumber")
        if seq:
            track["sequence_number"] = int(seq) if seq.isdigit() else seq

        # Resource reference (links to ReleaseList)
        ref = _text(sr, f"{prefix}ResourceReference")
        if ref:
            track["resource_reference"] = ref

        tracks.append(track)

    return tracks


def _extract_deals(deal_list: etree._Element, prefix: str) -> list[dict[str, Any]]:
    deals: list[dict[str, Any]] = []

    for rel_deal in deal_list.iter(f"{prefix}ReleaseDeal"):
        deal: dict[str, Any] = {}

        deal["release_reference"] = _text(rel_deal, f"{prefix}DealReleaseReference")

        deal_el = rel_deal.find(f"{prefix}Deal")
        if deal_el is not None:
            deal["deal_terms_type"] = _text(deal_el, f"{prefix}DealTerms/{prefix}CommercialModelType")
            deal["start_date"] = _text(deal_el, f"{prefix}DealTerms/{prefix}ValidityPeriod/{prefix}StartDate")
            deal["end_date"] = _text(deal_el, f"{prefix}DealTerms/{prefix}ValidityPeriod/{prefix}EndDate")
            deal["territory"] = _text(deal_el, f"{prefix}DealTerms/{prefix}TerritoryCode")
            deal["usage_types"] = [
                el.text.strip()
                for el in deal_el.iter(f"{prefix}UseType")
                if el.text
            ]

        deals.append({k: v for k, v in deal.items() if v is not None})

    return deals


def _iso8601_to_ms(duration: str) -> int | None:
    """Convert ISO 8601 duration (PT3M45S) to milliseconds."""
    m = re.match(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
        duration,
    )
    if not m:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = float(m.group(4) or 0)
    total_ms = int(
        (days * 86400 + hours * 3600 + minutes * 60 + seconds) * 1000
    )
    return total_ms
