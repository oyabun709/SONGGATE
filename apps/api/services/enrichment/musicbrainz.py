"""
MusicBrainz metadata enrichment service.

Enriches release metadata with authoritative data from the MusicBrainz
open database and validates ISRCs against MB recordings.

Lookup strategy
───────────────
enrich_release():
  1. For each ISRC in metadata.isrc_list → recording lookup (most reliable)
     - Extracts: composer credits, ISWC, label, genre tags
  2. Fallback to title + artist search if ISRCs yield no results
  3. Deduplicates suggestions; suppresses matches below confidence threshold

validate_isrc():
  1. Format check: ^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$
  2. MusicBrainz recording lookup by ISRC
  3. Cross-checks title/artist if provided
  4. Returns recording info if found, mismatch details if conflicting

Rate limiting
─────────────
musicbrainzngs enforces 1 req/s by default (MusicBrainz policy).
The client is configured with a descriptive User-Agent as required by
the MusicBrainz API terms of service.

Dependencies
────────────
Python: musicbrainzngs
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import musicbrainzngs

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# MusicBrainz client config
# ──────────────────────────────────────────────────────────────────────────────

_MB_CONFIGURED = False

def _ensure_mb_configured() -> None:
    global _MB_CONFIGURED
    if not _MB_CONFIGURED:
        musicbrainzngs.set_useragent(
            "songgate",
            "1.0",
            "https://songgate.vercel.app",
        )
        musicbrainzngs.set_rate_limit(limit_or_interval=1.0, new_requests=1)
        _MB_CONFIGURED = True


# ──────────────────────────────────────────────────────────────────────────────
# ISRC format
# ──────────────────────────────────────────────────────────────────────────────

# ISRC canonical: CC-XXX-YY-NNNNN (hyphens optional for lookup)
_ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
_ISRC_WITH_HYPHENS = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3}-[0-9]{2}-[0-9]{5}$")


def _normalize_isrc(isrc: str) -> str:
    """Strip hyphens and upper-case — returns bare 12-char ISRC."""
    return isrc.replace("-", "").upper()


def _is_valid_isrc_format(isrc: str) -> bool:
    return bool(_ISRC_PATTERN.match(_normalize_isrc(isrc)))


# ──────────────────────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EnrichmentSuggestion:
    """
    A single data enrichment suggestion derived from MusicBrainz.

    field:       Which metadata field this suggestion applies to.
    suggested:   The value from MusicBrainz.
    current:     The value currently in the release metadata (empty = not set).
    source_url:  MusicBrainz URL where this data was found.
    message:     Human-readable prompt shown in the UI.
    confidence:  "high" | "medium" | "low"
    """
    field: str
    suggested: str
    current: str
    source_url: str
    message: str
    confidence: str = "medium"   # "high" | "medium" | "low"
    mb_entity_id: str = ""       # MBID of the source recording/release/work


@dataclass
class EnrichmentResult:
    """
    Full enrichment result for a release.

    ``suggestions`` are additive — they do not overwrite existing data but
    surface potential improvements.  The caller decides which to apply.
    """
    # Raw MB data found
    mb_recording_ids: list[str] = field(default_factory=list)
    mb_release_ids: list[str] = field(default_factory=list)

    # Enriched fields (empty string = not found)
    composers: list[str] = field(default_factory=list)
    publisher: str = ""
    label: str = ""
    iswc: str = ""
    genres: list[str] = field(default_factory=list)

    # Actionable suggestions for the UI
    suggestions: list[EnrichmentSuggestion] = field(default_factory=list)

    # Diagnostics
    isrcs_searched: list[str] = field(default_factory=list)
    lookup_duration_seconds: float | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mb_recording_ids": self.mb_recording_ids,
            "mb_release_ids": self.mb_release_ids,
            "composers": self.composers,
            "publisher": self.publisher,
            "label": self.label,
            "iswc": self.iswc,
            "genres": self.genres,
            "suggestions": [
                {
                    "field": s.field,
                    "suggested": s.suggested,
                    "current": s.current,
                    "source_url": s.source_url,
                    "message": s.message,
                    "confidence": s.confidence,
                    "mb_entity_id": s.mb_entity_id,
                }
                for s in self.suggestions
            ],
            "isrcs_searched": self.isrcs_searched,
            "lookup_duration_seconds": self.lookup_duration_seconds,
            "errors": self.errors,
        }


@dataclass
class ISRCValidationResult:
    """
    Result of a single ISRC lookup in MusicBrainz.
    """
    isrc: str
    format_valid: bool
    exists_in_mb: bool = False

    # MB recording data if found
    mb_recording_id: str = ""
    mb_recording_title: str = ""
    mb_artist_name: str = ""

    # Mismatch detection
    has_mismatch: bool = False
    mismatch_details: list[str] = field(default_factory=list)

    # Full MB URL for reference
    mb_url: str = ""

    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "isrc": self.isrc,
            "format_valid": self.format_valid,
            "exists_in_mb": self.exists_in_mb,
            "mb_recording_id": self.mb_recording_id,
            "mb_recording_title": self.mb_recording_title,
            "mb_artist_name": self.mb_artist_name,
            "has_mismatch": self.has_mismatch,
            "mismatch_details": self.mismatch_details,
            "mb_url": self.mb_url,
            "errors": self.errors,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Enricher
# ──────────────────────────────────────────────────────────────────────────────

class MusicBrainzEnricher:
    """
    Enriches release metadata and validates ISRCs against MusicBrainz.

    Instantiate once per process; the underlying musicbrainzngs library
    handles rate limiting (1 req/s per MB policy).
    """

    # Title/artist similarity threshold for "same recording" confidence
    _TITLE_SIMILARITY_HIGH = 0.90
    _TITLE_SIMILARITY_MEDIUM = 0.70

    def __init__(self) -> None:
        _ensure_mb_configured()

    # ── enrich_release ────────────────────────────────────────────────────────

    def enrich_release(
        self,
        metadata: "ReleaseMetadata",  # noqa: F821
    ) -> EnrichmentResult:
        """
        Look up release data in MusicBrainz and return enrichment suggestions.

        Strategy:
          1. For each ISRC in metadata.isrc_list → recording lookup
          2. Fallback: title + artist text search if ISRCs yield nothing
        """
        result = EnrichmentResult()
        t0 = time.perf_counter()

        try:
            # ── Phase 1: ISRC-based recording lookup ──
            found_via_isrc = False
            for isrc in metadata.isrc_list:
                norm = _normalize_isrc(isrc)
                if not _is_valid_isrc_format(norm):
                    continue
                result.isrcs_searched.append(norm)
                try:
                    self._enrich_from_isrc(norm, metadata, result)
                    found_via_isrc = True
                except musicbrainzngs.ResponseError as exc:
                    if "404" in str(exc):
                        pass  # ISRC not in MB — normal
                    else:
                        result.errors.append(f"MB ISRC lookup error ({norm}): {exc}")
                except musicbrainzngs.NetworkError as exc:
                    result.errors.append(f"MB network error: {exc}")

            # ── Phase 2: fallback to title + artist search ──
            if not found_via_isrc and metadata.title and metadata.artist:
                try:
                    self._enrich_from_search(metadata, result)
                except musicbrainzngs.ResponseError as exc:
                    result.errors.append(f"MB search error: {exc}")
                except musicbrainzngs.NetworkError as exc:
                    result.errors.append(f"MB network error: {exc}")

            # ── Deduplicate composers / genres ──
            result.composers = _dedup(result.composers)
            result.genres = _dedup(result.genres)

        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Unexpected enrichment error: {exc}")
            logger.exception("MusicBrainzEnricher.enrich_release() failed")
        finally:
            result.lookup_duration_seconds = round(time.perf_counter() - t0, 3)

        return result

    # ── validate_isrc ─────────────────────────────────────────────────────────

    def validate_isrc(
        self,
        isrc: str,
        expected_title: str | None = None,
        expected_artist: str | None = None,
    ) -> ISRCValidationResult:
        """
        Validate an ISRC: format check + MusicBrainz lookup.

        If expected_title / expected_artist are provided, cross-checks the
        MB recording data for mismatches.
        """
        norm = _normalize_isrc(isrc)
        result = ISRCValidationResult(isrc=isrc, format_valid=_is_valid_isrc_format(norm))

        if not result.format_valid:
            result.errors.append(
                f"Invalid ISRC format '{isrc}'. "
                f"Expected: CC-XXX-YY-NNNNN (e.g. USRC12345678)."
            )
            return result

        try:
            _ensure_mb_configured()
            data = musicbrainzngs.get_recordings_by_isrc(
                norm,
                includes=["artist-credits", "releases"],
            )
            recordings = data.get("isrc", {}).get("recording-list", [])
        except musicbrainzngs.ResponseError as exc:
            if "404" in str(exc):
                result.exists_in_mb = False
                return result
            result.errors.append(f"MusicBrainz lookup failed: {exc}")
            return result
        except musicbrainzngs.NetworkError as exc:
            result.errors.append(f"MusicBrainz network error: {exc}")
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Unexpected error: {exc}")
            return result

        if not recordings:
            result.exists_in_mb = False
            return result

        # Use the first (most canonical) recording
        rec = recordings[0]
        rec_id = rec.get("id", "")
        rec_title = rec.get("title", "")
        artist_credits = rec.get("artist-credit", [])
        mb_artist = _flatten_artist_credits(artist_credits)

        result.exists_in_mb = True
        result.mb_recording_id = rec_id
        result.mb_recording_title = rec_title
        result.mb_artist_name = mb_artist
        result.mb_url = f"https://musicbrainz.org/recording/{rec_id}" if rec_id else ""

        # ── Mismatch detection ──
        if expected_title:
            sim = _similarity(rec_title, expected_title)
            if sim < self._TITLE_SIMILARITY_MEDIUM:
                result.has_mismatch = True
                result.mismatch_details.append(
                    f"Title mismatch: ISRC {norm} points to '{rec_title}' in MusicBrainz, "
                    f"but release has '{expected_title}' (similarity: {sim:.0%})."
                )

        if expected_artist and mb_artist:
            sim = _similarity(mb_artist, expected_artist)
            if sim < self._TITLE_SIMILARITY_MEDIUM:
                result.has_mismatch = True
                result.mismatch_details.append(
                    f"Artist mismatch: ISRC {norm} is registered to '{mb_artist}' in MusicBrainz, "
                    f"but release credits '{expected_artist}' (similarity: {sim:.0%})."
                )

        return result

    # ── private helpers ────────────────────────────────────────────────────────

    def _enrich_from_isrc(
        self,
        isrc: str,
        metadata: "ReleaseMetadata",
        result: EnrichmentResult,
    ) -> None:
        """
        Fetch recording data for one ISRC and merge findings into result.
        Includes: composer credits, ISWC, label, genre tags.
        """
        data = musicbrainzngs.get_recordings_by_isrc(
            isrc,
            includes=["artists", "releases", "work-rels", "tags"],
        )
        recordings = data.get("isrc", {}).get("recording-list", [])
        if not recordings:
            return

        rec = recordings[0]
        rec_id = rec.get("id", "")
        rec_title = rec.get("title", "")

        if rec_id and rec_id not in result.mb_recording_ids:
            result.mb_recording_ids.append(rec_id)

        # Tags / genres
        for tag in rec.get("tag-list", []):
            name = tag.get("name", "")
            if name and name not in result.genres:
                result.genres.append(name)

        # Work relationships → composers + ISWC
        for rel in rec.get("relation-list", []):
            if rel.get("target-type") != "work":
                continue
            for work_rel in rel.get("relation", []):
                self._extract_work_data(work_rel.get("work", {}), metadata, result, rec_id)

        # Release relationships → label
        for release in rec.get("release-list", []):
            release_id = release.get("id", "")
            if release_id and release_id not in result.mb_release_ids:
                result.mb_release_ids.append(release_id)
            # Fetch full release info to get label (only on first release)
            if len(result.mb_release_ids) == 1:
                try:
                    self._enrich_label_from_release(release_id, metadata, result)
                except Exception:  # noqa: BLE001
                    pass  # Label is enrichment-only; don't fail on it

    def _extract_work_data(
        self,
        work: dict,
        metadata: "ReleaseMetadata",
        result: EnrichmentResult,
        recording_id: str,
    ) -> None:
        """Extract ISWC and composer credits from a MB Work entity."""
        work_id = work.get("id", "")
        mb_url = f"https://musicbrainz.org/work/{work_id}" if work_id else ""

        # ISWC
        iswc = work.get("iswc", "")
        if iswc and not result.iswc:
            result.iswc = iswc
            current_iswc = getattr(metadata, "iswc", "")
            if not current_iswc:
                result.suggestions.append(EnrichmentSuggestion(
                    field="iswc",
                    suggested=iswc,
                    current="",
                    source_url=mb_url,
                    message=(
                        f"ISWC found in MusicBrainz: {iswc}. "
                        f"Add to release for publishing royalty tracking."
                    ),
                    confidence="high",
                    mb_entity_id=work_id,
                ))

        # Composer / songwriter credits from work relations
        for rel_list in work.get("relation-list", []):
            if not isinstance(rel_list, dict):
                continue
            for rel in rel_list.get("relation", []):
                rel_type = rel.get("type", "").lower()
                if rel_type not in ("composer", "lyricist", "writer", "arranger"):
                    continue
                artist = rel.get("artist", {})
                name = artist.get("name", "") or artist.get("sort-name", "")
                if name and name not in result.composers:
                    result.composers.append(name)

        # Generate composer suggestion if we found names not in current metadata
        current_composers = set(getattr(metadata, "composers", []))
        new_composers = [c for c in result.composers if c not in current_composers]
        if new_composers:
            # Only emit one suggestion per work, not per composer
            result.suggestions.append(EnrichmentSuggestion(
                field="composers",
                suggested=", ".join(new_composers),
                current=", ".join(sorted(current_composers)) if current_composers else "",
                source_url=mb_url,
                message=(
                    f"MusicBrainz shows composer(s): {', '.join(new_composers)}. "
                    f"Add to release for publishing accuracy?"
                ),
                confidence="high" if len(new_composers) == 1 else "medium",
                mb_entity_id=work_id,
            ))

    def _enrich_label_from_release(
        self,
        release_id: str,
        metadata: "ReleaseMetadata",
        result: EnrichmentResult,
    ) -> None:
        """
        Fetch a full release record to extract the label name.
        Makes an additional MB API call — only done once per enrichment run.
        """
        if not release_id:
            return
        release_data = musicbrainzngs.get_release_by_id(
            release_id, includes=["labels"]
        )
        release = release_data.get("release", {})
        mb_url = f"https://musicbrainz.org/release/{release_id}"

        for li in release.get("label-info-list", []):
            label = li.get("label", {})
            name = label.get("name", "")
            if name:
                result.label = name
                current_label = getattr(metadata, "label", "")
                if not current_label:
                    result.suggestions.append(EnrichmentSuggestion(
                        field="label",
                        suggested=name,
                        current="",
                        source_url=mb_url,
                        message=(
                            f"Label '{name}' found in MusicBrainz. "
                            f"Add to release metadata?"
                        ),
                        confidence="medium",
                        mb_entity_id=release_id,
                    ))
                elif _similarity(name, current_label) < 0.7:
                    result.suggestions.append(EnrichmentSuggestion(
                        field="label",
                        suggested=name,
                        current=current_label,
                        source_url=mb_url,
                        message=(
                            f"MusicBrainz shows label '{name}', "
                            f"but release has '{current_label}'. Verify?"
                        ),
                        confidence="low",
                        mb_entity_id=release_id,
                    ))
                break  # First label is sufficient

    def _enrich_from_search(
        self,
        metadata: "ReleaseMetadata",
        result: EnrichmentResult,
    ) -> None:
        """
        Fallback: search MB by title + artist when ISRCs yield nothing.
        Lower confidence — title/artist strings can match multiple recordings.
        """
        search_results = musicbrainzngs.search_recordings(
            recording=metadata.title,
            artist=metadata.artist,
            limit=5,
        )
        recordings = search_results.get("recording-list", [])
        if not recordings:
            return

        # Find the best title+artist match
        best_rec = None
        best_score = 0.0
        for rec in recordings:
            rec_title = rec.get("title", "")
            artist_credits = rec.get("artist-credit", [])
            rec_artist = _flatten_artist_credits(artist_credits)
            score = (
                _similarity(rec_title, metadata.title) * 0.6
                + _similarity(rec_artist, metadata.artist) * 0.4
            )
            if score > best_score:
                best_score = score
                best_rec = rec

        if best_rec is None or best_score < self._TITLE_SIMILARITY_MEDIUM:
            return

        rec_id = best_rec.get("id", "")
        confidence = "high" if best_score >= self._TITLE_SIMILARITY_HIGH else "medium"

        if rec_id and rec_id not in result.mb_recording_ids:
            result.mb_recording_ids.append(rec_id)

        # Tags
        for tag in best_rec.get("tag-list", []):
            name = tag.get("name", "")
            if name and name not in result.genres:
                result.genres.append(name)

        if result.genres:
            current_genre = getattr(metadata, "genre", "")
            if not current_genre:
                result.suggestions.append(EnrichmentSuggestion(
                    field="genre",
                    suggested=result.genres[0],
                    current="",
                    source_url=f"https://musicbrainz.org/recording/{rec_id}",
                    message=(
                        f"MusicBrainz genre tag: '{result.genres[0]}'. "
                        f"Add as primary genre?"
                    ),
                    confidence=confidence,
                    mb_entity_id=rec_id,
                ))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _flatten_artist_credits(credits: list) -> str:
    """
    Flatten MB artist-credit list → plain artist string.

    MB artist-credit is a heterogeneous list of:
      {"artist": {"name": "..."}, "joinphrase": " feat. "}
      or plain strings (join phrases embedded in older responses)
    """
    parts: list[str] = []
    for item in credits:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            artist = item.get("artist", {})
            name = artist.get("name", "") or artist.get("sort-name", "")
            if name:
                parts.append(name)
            join = item.get("joinphrase", "")
            if join:
                parts.append(join)
    return "".join(parts).strip()


def _similarity(a: str, b: str) -> float:
    """
    String similarity ratio in [0, 1].

    Uses SequenceMatcher on lower-cased strings.  Fast enough for
    small N (< 10 comparisons per enrichment run).
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _dedup(lst: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
