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

        # When the root element carries the namespace but child elements were
        # written without a prefix (xmlns:ern= style), fall back to no-prefix.
        def _find(parent: etree._Element, tag: str) -> etree._Element | None:
            el = parent.find(f"{prefix}{tag}")
            if el is None and prefix:
                el = parent.find(tag)
            return el

        def _findall(parent: etree._Element, tag: str) -> list[etree._Element]:
            els = parent.findall(f"{prefix}{tag}")
            if not els and prefix:
                els = parent.findall(tag)
            return els

        meta: dict[str, Any] = {
            "version": _detect_ern_version(root),
            "profile": _detect_profile(root, prefix),
        }

        # MessageHeader
        header = _find(root, "MessageHeader")
        if header is not None:
            meta["sender_party_id"] = _text(header, f"{prefix}SentOnBehalfOf/{prefix}PartyId") or \
                                      _text(header, "SentOnBehalfOf/PartyId")
            meta["sender_name"] = _text(header, f"{prefix}SentOnBehalfOf/{prefix}PartyName/{prefix}FullName") or \
                                   _text(header, "SentOnBehalfOf/PartyName/FullName") or \
                                   _text(header, f"{prefix}MessageSender/{prefix}PartyName/{prefix}FullName") or \
                                   _text(header, "MessageSender/PartyName/FullName")
            meta["message_id"] = _text(header, f"{prefix}MessageId") or _text(header, "MessageId")
            meta["message_created"] = _text(header, f"{prefix}MessageCreatedDateTime") or \
                                      _text(header, "MessageCreatedDateTime")

        # ReleaseList — grab the primary release
        release_list = _find(root, "ReleaseList")
        if release_list is not None:
            releases = _findall(release_list, "Release")
            primary = None
            for rel in releases:
                is_main = rel.get("IsMainRelease") or \
                          rel.findtext(f"{prefix}IsMainRelease") or \
                          rel.findtext("IsMainRelease") or ""
                if is_main.lower() == "true":
                    primary = rel
                    break
            if primary is None and releases:
                primary = releases[0]

            if primary is not None:
                meta.update(_extract_release_fields(primary, prefix))

        # ResourceList — collect tracks / sound recordings + artwork dims
        resource_list = _find(root, "ResourceList")
        if resource_list is not None:
            tracks, artwork = _extract_tracks(resource_list, prefix)
            meta["tracks"] = tracks
            meta.update(artwork)  # artwork_width, artwork_height if found

        # Build isrc_list for the rules engine
        meta["isrc_list"] = [t["isrc"] for t in meta.get("tracks", []) if "isrc" in t]

        # Aggregate top-level publisher from tracks (first track with has_publisher=True)
        if not meta.get("publisher"):
            for t in meta.get("tracks", []):
                if t.get("has_publisher") and t.get("publisher"):
                    meta["publisher"] = t["publisher"]
                    break

        # DealList
        deal_list = _find(root, "DealList")
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
        # Try namespaced lookup first, then fall back to un-namespaced.
        # Real-world DDEX files often declare the namespace only on the root
        # element with a prefix (xmlns:ern=...) leaving child elements without
        # explicit namespace decoration — both forms are structurally valid.
        found = root.find(f"{prefix}{el_name}")
        if found is None and prefix:
            found = root.find(el_name)
        if found is None:
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

    isrc_elements = list(root.iter(f"{prefix}ISRC")) + list(root.iter(f"{prefix}IsRC"))
    if not isrc_elements and prefix:
        isrc_elements = list(root.iter("ISRC")) + list(root.iter("IsRC"))

    for el in isrc_elements:
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

    upc_elements = list(root.iter(f"{prefix}UPC"))
    if not upc_elements and prefix:
        upc_elements = list(root.iter("UPC"))

    for el in upc_elements:
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
    if header is None and prefix:
        header = root.find("MessageHeader")
    if header is None:
        return findings  # already caught by _check_required_elements

    child_prefix = prefix if header.find(f"{prefix}MessageId") is not None else ""
    required_header_fields = ["MessageId", "MessageSender", "MessageRecipient", "MessageCreatedDateTime"]
    for field_name in required_header_fields:
        if header.find(f"{child_prefix}{field_name}") is None:
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
    """
    Extract fields from a <Release> element.

    DDEX ERN 4.x splits fields between the Release root and
    <ReleaseDetailsByTerritory>.  We search both, preferring the
    territory details block (which holds the display/delivery values).
    """
    data: dict[str, Any] = {}

    # Find ReleaseDetailsByTerritory — prefer "Worldwide", fall back to first
    details_els = list(release.iter(f"{prefix}ReleaseDetailsByTerritory"))
    if not details_els and prefix:
        details_els = list(release.iter("ReleaseDetailsByTerritory"))
    details: etree._Element | None = None
    for d in details_els:
        tc = d.findtext(f"{prefix}TerritoryCode") or d.findtext("TerritoryCode") or ""
        if tc.lower() in ("worldwide", "ww", "001"):
            details = d
            break
    if details is None and details_els:
        details = details_els[0]

    # Helper: search release root then details block
    def _get(tag: str) -> str | None:
        for el in ([release, details] if details is not None else [release]):
            v = el.findtext(f"{prefix}{tag}") or el.findtext(tag)
            if v and v.strip():
                return v.strip()
        return None

    def _find_el(tag: str) -> etree._Element | None:
        for el in ([release, details] if details is not None else [release]):
            found = el.find(f"{prefix}{tag}") or el.find(tag)
            if found is not None:
                return found
        return None

    # Release reference
    ref = _get("ReleaseReference")
    if ref:
        data["release_reference"] = ref

    # GRid
    rid = _find_el("ReleaseId")
    if rid is not None:
        grid = rid.findtext(f"{prefix}GRid") or rid.findtext("GRid")
        if grid:
            data["grid"] = grid.strip()
        upc = (rid.findtext(f"{prefix}ICPN/{prefix}UPC") or
               rid.findtext("ICPN/UPC") or
               rid.findtext(f"{prefix}ICPN") or
               rid.findtext("ICPN"))
        if upc and upc.strip():
            data["upc"] = upc.strip()

    # Title — ReferenceTitle first, then display Title
    for title_path in (
        f"{prefix}ReferenceTitle/{prefix}TitleText", "ReferenceTitle/TitleText",
        f"{prefix}Title/{prefix}TitleText", "Title/TitleText",
    ):
        title = release.findtext(title_path)
        if not title and details is not None:
            title = details.findtext(title_path)
        if title and title.strip():
            data["title"] = title.strip()
            break

    # Artist — DisplayArtistName shortcut, then DisplayArtist/PartyName/FullName
    for search_el in ([details, release] if details is not None else [release]):
        if search_el is None:
            continue
        dan = search_el.findtext(f"{prefix}DisplayArtistName") or search_el.findtext("DisplayArtistName")
        if dan and dan.strip():
            data["artist"] = dan.strip()
            break
        for da in search_el.iter(f"{prefix}DisplayArtist"):
            fn = da.findtext(f"{prefix}PartyName/{prefix}FullName") or da.findtext("PartyName/FullName")
            if fn and fn.strip():
                data["artist"] = fn.strip()
                break
        if "artist" in data:
            break

    # Release date — OriginalReleaseDate preferred, then ReleaseDate
    for tag in ("OriginalReleaseDate", "ReleaseDate"):
        rd = _get(tag)
        if rd:
            data["release_date"] = rd
            break

    # Release type
    rt = _get("ReleaseType")
    if rt:
        data["release_type"] = rt

    # Label
    label = _get("LabelName")
    if label:
        data["label"] = label

    # CLine
    c = None
    for search_el in ([details, release] if details is not None else [release]):
        if search_el is None:
            continue
        # Try nested CLine/CLineText first (ERN 4.x style)
        for cline_el in list(search_el.iter(f"{prefix}CLine")) + list(search_el.iter("CLine")):
            ct = cline_el.findtext(f"{prefix}CLineText") or cline_el.findtext("CLineText") or \
                 (cline_el.text or "").strip()
            if ct and ct.strip():
                c = ct.strip()
                break
        if c:
            break
    if c:
        data["c_line"] = c

    # PLine
    p = None
    p_year = None
    for search_el in ([details, release] if details is not None else [release]):
        if search_el is None:
            continue
        for pline_el in list(search_el.iter(f"{prefix}PLine")) + list(search_el.iter("PLine")):
            py = pline_el.findtext(f"{prefix}Year") or pline_el.findtext("Year")
            if py and py.strip():
                p_year = py.strip()
            pt = pline_el.findtext(f"{prefix}PLineText") or pline_el.findtext("PLineText") or \
                 (pline_el.text or "").strip()
            if pt and pt.strip():
                p = pt.strip()
                break
        if p:
            break
    if p:
        data["p_line"] = p
    if p_year:
        data["p_line_year"] = p_year

    # Genre
    for search_el in ([details, release] if details is not None else [release]):
        if search_el is None:
            continue
        for genre_tag in (f"{prefix}Genre", "Genre", f"{prefix}MainGenre", "MainGenre"):
            genre_el = search_el.find(genre_tag)
            if genre_el is not None:
                gt = genre_el.findtext(f"{prefix}GenreText") or genre_el.findtext("GenreText")
                if gt and gt.strip():
                    data["genre"] = gt.strip()
                    break
        if "genre" in data:
            break

    # Parental warning
    pw = _get("ParentalWarningType")
    if pw:
        data["parental_warning"] = pw

    return {k: v for k, v in data.items() if v is not None}


def _ft(el: etree._Element, prefix: str, *paths: str) -> str | None:
    """Find text with namespace fallback across multiple candidate paths."""
    for path in paths:
        v = el.findtext(f"{prefix}{path}") if prefix else None
        if v and v.strip():
            return v.strip()
        v = el.findtext(path)
        if v and v.strip():
            return v.strip()
    return None


def _extract_tracks(resource_list: etree._Element, prefix: str) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []

    # Try namespaced iter first; fall back to un-namespaced when child elements
    # carry no namespace (xmlns:ern= prefix-only declaration on root).
    sound_recordings = list(resource_list.iter(f"{prefix}SoundRecording"))
    if not sound_recordings and prefix:
        sound_recordings = list(resource_list.iter("SoundRecording"))

    for sr in sound_recordings:
        track: dict[str, Any] = {}

        # ISRC
        isrc = _ft(sr, prefix,
                   f"SoundRecordingId/ISRC",
                   f"SoundRecordingId/{prefix}ISRC") or \
               (sr.findtext(f"{prefix}SoundRecordingId/{prefix}ISRC") or "").strip() or None
        # Simpler: just iterate ISRC elements inside this SoundRecording
        # Handle both <ISRC> and <IsRC> (case variants in the wild)
        for isrc_el in (list(sr.iter(f"{prefix}ISRC")) + list(sr.iter(f"{prefix}IsRC")) +
                        list(sr.iter("ISRC")) + list(sr.iter("IsRC"))):
            v = (isrc_el.text or "").strip()
            if v:
                isrc = v
                break
        if isrc:
            track["isrc"] = isrc

        # Title
        title = (_ft(sr, prefix, "ReferenceTitle/TitleText") or
                 _ft(sr, prefix, "Title/TitleText"))
        if title:
            track["title"] = title

        # Duration (ISO 8601 — PT3M45S)
        duration = _ft(sr, prefix, "Duration")
        if duration:
            track["duration_iso"] = duration
            track["duration_ms"] = _iso8601_to_ms(duration)
            track["duration_s"] = round(_iso8601_to_ms(duration) / 1000) if _iso8601_to_ms(duration) else None

        # Publisher — check DisplayPublisher or Contributor with Role=MusicPublisher
        publisher_els = list(sr.iter(f"{prefix}DisplayPublisher")) + list(sr.iter("DisplayPublisher"))
        if publisher_els:
            pub_name = _ft(publisher_els[0], prefix, "PartyName/FullName")
            if pub_name:
                track["publisher"] = pub_name
        # Also check <Contributor><Role>MusicPublisher</Role> pattern (ERN 4.x)
        if not publisher_els:
            for contrib in (list(sr.iter(f"{prefix}Contributor")) + list(sr.iter("Contributor"))):
                role = (contrib.findtext(f"{prefix}Role") or contrib.findtext("Role") or "").strip()
                if role == "MusicPublisher":
                    pub_name = (contrib.findtext(f"{prefix}PartyName/{prefix}FullName") or
                                contrib.findtext("PartyName/FullName") or "").strip()
                    if pub_name:
                        track["publisher"] = pub_name
                    publisher_els = [contrib]
                    break
        track["has_publisher"] = bool(publisher_els)

        # Artist
        for da in list(sr.iter(f"{prefix}DisplayArtist")) + list(sr.iter("DisplayArtist")):
            name = _ft(da, prefix, "PartyName/FullName")
            if name:
                track["artist"] = name
                break

        # Resource reference
        ref = _ft(sr, prefix, "ResourceReference")
        if ref:
            track["resource_reference"] = ref

        tracks.append(track)

    # Also extract artwork dimensions from Image resources in the same ResourceList
    image_els = list(resource_list.iter(f"{prefix}Image")) + list(resource_list.iter("Image"))
    artwork: dict[str, Any] = {}
    for img in image_els:
        img_type = _ft(img, prefix, "ImageType")
        if img_type and "front" not in img_type.lower() and "cover" not in img_type.lower():
            continue
        # ImageHeight/ImageWidth may be nested inside ImageDetailsByTerritory
        for h_tag in (f"{prefix}ImageHeight", "ImageHeight"):
            el = next(img.iter(h_tag), None)
            if el is not None and (el.text or "").strip():
                try:
                    artwork["artwork_height"] = int(el.text.strip())
                except ValueError:
                    pass
                break
        for w_tag in (f"{prefix}ImageWidth", "ImageWidth"):
            el = next(img.iter(w_tag), None)
            if el is not None and (el.text or "").strip():
                try:
                    artwork["artwork_width"] = int(el.text.strip())
                except ValueError:
                    pass
                break
        if artwork:
            break  # use first matching image

    return tracks, artwork


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
