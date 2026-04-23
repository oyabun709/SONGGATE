"""
JSON ingestion parser for DDEX-lite / flat metadata payloads.

See docs/json_template.json for the expected schema.  The parser is
intentionally lenient — it collects findings but still returns whatever
data it could extract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .validator import DDEXFinding, _ISRC_RE, _UPC_RE

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class JSONParseResult:
    """Result of parsing a metadata JSON payload."""
    releases: list[dict[str, Any]] = field(default_factory=list)
    findings: list[DDEXFinding] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(f.severity in ("critical", "error") for f in self.findings)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class JSONParser:
    """
    Parse a DDEX-lite JSON metadata file.

    Accepts either:
      - A single release object: ``{ "upc": "...", "title": "...", "tracks": [...] }``
      - An array of release objects: ``[{ ... }, { ... }]``
    """

    def parse(self, content: bytes) -> JSONParseResult:
        """
        Parse JSON bytes and return metadata + findings.

        Args:
            content: Raw JSON bytes (UTF-8).

        Returns:
            JSONParseResult with releases list and validation findings.
        """
        result = JSONParseResult()

        # Decode
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            result.findings.append(
                DDEXFinding(
                    rule_id="json.encoding",
                    severity="critical",
                    message="JSON file is not valid UTF-8.",
                )
            )
            return result

        # Parse JSON
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            result.findings.append(
                DDEXFinding(
                    rule_id="json.parse",
                    severity="critical",
                    message=f"JSON parse error: {exc}",
                    fix_hint="Validate JSON syntax with a linter.",
                    line=exc.lineno,
                    column=exc.colno,
                )
            )
            return result

        # Normalise to list of releases
        if isinstance(payload, dict):
            releases_raw = [payload]
        elif isinstance(payload, list):
            releases_raw = payload
        else:
            result.findings.append(
                DDEXFinding(
                    rule_id="json.structure",
                    severity="critical",
                    message="JSON must be a release object or an array of release objects.",
                )
            )
            return result

        for idx, raw in enumerate(releases_raw):
            release_findings, release = self._parse_release(raw, idx)
            result.findings.extend(release_findings)
            if release:
                result.releases.append(release)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_release(
        self, raw: Any, idx: int
    ) -> tuple[list[DDEXFinding], dict[str, Any] | None]:
        findings: list[DDEXFinding] = []
        prefix = f"releases[{idx}]"

        if not isinstance(raw, dict):
            findings.append(
                DDEXFinding(
                    rule_id="json.release_type",
                    severity="error",
                    message=f"{prefix}: each release must be a JSON object.",
                )
            )
            return findings, None

        release: dict[str, Any] = {}

        # --- required scalar fields ---
        required_scalars = {
            "upc": "UPC / EAN barcode",
            "title": "release title",
            "artist": "primary artist name",
            "label": "label name",
            "release_date": "release date (YYYY-MM-DD)",
        }
        for key, label in required_scalars.items():
            val = raw.get(key)
            if not val:
                findings.append(
                    DDEXFinding(
                        rule_id=f"json.missing_{key}",
                        severity="error",
                        message=f"{prefix}: missing required field '{key}' ({label}).",
                        field_path=f"{prefix}.{key}",
                        fix_hint=f"Add '{key}' to the release object.",
                    )
                )
            else:
                release[key] = str(val).strip()

        # --- UPC format ---
        upc = release.get("upc", "")
        if upc and not _UPC_RE.match(upc):
            findings.append(
                DDEXFinding(
                    rule_id="json.upc_format",
                    severity="error",
                    message=f"{prefix}: invalid UPC '{upc}' — must be 12 or 13 digits.",
                    field_path=f"{prefix}.upc",
                    actual_value=upc,
                    fix_hint="UPC-A is 12 digits; EAN-13 is 13 digits.",
                )
            )

        # --- release_date format ---
        release_date = release.get("release_date", "")
        if release_date and not _DATE_RE.match(release_date):
            findings.append(
                DDEXFinding(
                    rule_id="json.date_format",
                    severity="error",
                    message=f"{prefix}: release_date '{release_date}' must be YYYY-MM-DD.",
                    field_path=f"{prefix}.release_date",
                    actual_value=release_date,
                )
            )

        # --- optional release fields ---
        for opt in (
            "release_type", "genre", "parental_warning",
            "c_line", "p_line", "language", "publisher",
        ):
            val = raw.get(opt)
            if val is not None:
                release[opt] = str(val).strip()

        # --- deals ---
        deals_raw = raw.get("deals")
        if deals_raw is not None:
            deal_findings, deals = self._parse_deals(deals_raw, prefix)
            findings.extend(deal_findings)
            release["deals"] = deals

        # --- tracks ---
        tracks_raw = raw.get("tracks")
        if not tracks_raw:
            findings.append(
                DDEXFinding(
                    rule_id="json.no_tracks",
                    severity="error",
                    message=f"{prefix}: release must have at least one track.",
                    field_path=f"{prefix}.tracks",
                    fix_hint="Add a 'tracks' array with at least one track object.",
                )
            )
            release["tracks"] = []
        else:
            track_findings, tracks = self._parse_tracks(tracks_raw, prefix)
            findings.extend(track_findings)
            release["tracks"] = tracks

        return findings, release

    def _parse_tracks(
        self, tracks_raw: Any, release_prefix: str
    ) -> tuple[list[DDEXFinding], list[dict[str, Any]]]:
        findings: list[DDEXFinding] = []
        tracks: list[dict[str, Any]] = []

        if not isinstance(tracks_raw, list):
            findings.append(
                DDEXFinding(
                    rule_id="json.tracks_type",
                    severity="error",
                    message=f"{release_prefix}.tracks must be an array.",
                )
            )
            return findings, tracks

        for tidx, traw in enumerate(tracks_raw):
            tprefix = f"{release_prefix}.tracks[{tidx}]"
            if not isinstance(traw, dict):
                findings.append(
                    DDEXFinding(
                        rule_id="json.track_type",
                        severity="error",
                        message=f"{tprefix}: each track must be a JSON object.",
                    )
                )
                continue

            track: dict[str, Any] = {}

            # Required track fields
            for key in ("isrc", "title"):
                val = traw.get(key)
                if not val:
                    findings.append(
                        DDEXFinding(
                            rule_id=f"json.track.missing_{key}",
                            severity="error",
                            message=f"{tprefix}: missing required field '{key}'.",
                            field_path=f"{tprefix}.{key}",
                        )
                    )
                else:
                    track[key] = str(val).strip()

            # ISRC format
            isrc = track.get("isrc", "")
            if isrc and not _ISRC_RE.match(isrc):
                findings.append(
                    DDEXFinding(
                        rule_id="json.track.isrc_format",
                        severity="error",
                        message=f"{tprefix}: invalid ISRC '{isrc}'.",
                        field_path=f"{tprefix}.isrc",
                        actual_value=isrc,
                        fix_hint="ISRC must match CC-XXX-YY-NNNNN.",
                    )
                )

            # track_number
            tn_raw = traw.get("track_number")
            if tn_raw is not None:
                try:
                    track["track_number"] = int(tn_raw)
                except (TypeError, ValueError):
                    findings.append(
                        DDEXFinding(
                            rule_id="json.track.track_number",
                            severity="warning",
                            message=f"{tprefix}: track_number '{tn_raw}' should be an integer.",
                            field_path=f"{tprefix}.track_number",
                            actual_value=str(tn_raw),
                        )
                    )

            # duration_ms
            dur_raw = traw.get("duration_ms")
            if dur_raw is not None:
                try:
                    track["duration_ms"] = int(dur_raw)
                except (TypeError, ValueError):
                    findings.append(
                        DDEXFinding(
                            rule_id="json.track.duration_ms",
                            severity="warning",
                            message=f"{tprefix}: duration_ms '{dur_raw}' should be an integer.",
                            field_path=f"{tprefix}.duration_ms",
                        )
                    )

            # Optional track fields
            for opt in ("composer", "lyricist", "producer", "mix_engineer",
                        "explicit", "language", "track_version"):
                val = traw.get(opt)
                if val is not None:
                    track[opt] = val

            tracks.append(track)

        return findings, tracks

    def _parse_deals(
        self, deals_raw: Any, release_prefix: str
    ) -> tuple[list[DDEXFinding], list[dict[str, Any]]]:
        findings: list[DDEXFinding] = []
        deals: list[dict[str, Any]] = []

        if not isinstance(deals_raw, list):
            findings.append(
                DDEXFinding(
                    rule_id="json.deals_type",
                    severity="warning",
                    message=f"{release_prefix}.deals must be an array.",
                )
            )
            return findings, deals

        for didx, draw in enumerate(deals_raw):
            if not isinstance(draw, dict):
                continue
            deal: dict[str, Any] = {}
            for key in ("territory", "commercial_model", "use_type", "start_date", "end_date"):
                val = draw.get(key)
                if val is not None:
                    deal[key] = val
            deals.append(deal)

        return findings, deals
