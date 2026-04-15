"""
Fraud pre-screening service.

Runs a battery of heuristic checks against release metadata and returns a list
of FraudSignal objects.  Signals are advisory by default — only signals where
advisory=False should block automatic ingestion.

Detection layers
────────────────
1. Functional music spam     — keyword matching + volume + duration uniformity
2. Artist name similarity    — Levenshtein distance against known artists
3. Unicode homoglyphs        — Cyrillic/Latin script mixing in artist name
4. Release velocity          — DB-backed per-artist / per-org rate checks
5. Generic track titles      — placeholder title pattern matching
6. AI generation indicators  — missing credits + formulaic naming + known AI tools
7. Duplicate ISRCs           — ISRC reuse across different releases (DB lookup)

DB-dependent checks (velocity, duplicates) require an async SQLAlchemy session
passed as the `db` parameter to `screen()`.  If `db` is None those checks are
skipped and the returned signals include a note that the check was deferred.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FraudSignal:
    """
    A single fraud detection signal.

    All signals carry:
    - Plain-English explanation of WHY the content was flagged
    - Confidence level (low / medium / high)
    - Whether the signal is advisory (informational) or a hard block
    - A resolution path (concrete steps to clear the flag)
    """
    signal_id: str
    confidence: str            # "low" | "medium" | "high"
    explanation: str           # human-readable, specific to this metadata
    resolution: str            # how to clear this flag (from YAML definition)
    is_advisory: bool          # True = advisory note; False = hard block
    severity: str              # "critical" | "warning" | "info"
    matched_value: str = ""    # the specific value that triggered the signal
    category: str = ""         # "spam" | "impersonation" | "ai_content" | "duplicate"
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.is_advisory and self.confidence == "low":
            # Hard blocks must have at least medium confidence
            self.confidence = "medium"


@dataclass
class SignalDefinition:
    """A signal type loaded from signals.yaml."""
    id: str
    name: str
    category: str
    severity: str
    advisory: bool
    description: str
    resolution: str


@dataclass
class VelocityContext:
    """
    Pre-fetched release velocity counts.

    The pipeline task queries these from the DB before calling screen(),
    keeping the screener decoupled from the database layer.
    """
    releases_by_artist_30d: int = 0   # same artist name in last 30 days
    releases_by_org_7d: int = 0       # same org in last 7 days


# ──────────────────────────────────────────────────────────────────────────────
# Homoglyph mapping — characters that look like ASCII but aren't
# ──────────────────────────────────────────────────────────────────────────────

# Cyrillic → Latin confusables (and a few Greek/other lookalikes)
_HOMOGLYPH_MAP: dict[str, str] = {
    # Cyrillic lowercase
    "\u0430": "a",   # а → a
    "\u0435": "e",   # е → e
    "\u043e": "o",   # о → o
    "\u0440": "p",   # р → p
    "\u0441": "c",   # с → c
    "\u0445": "x",   # х → x
    "\u0443": "y",   # у → y
    "\u0438": "u",   # и (approx) → u (not exact but visually close in some fonts)
    "\u04cf": "l",   # ӏ → l
    "\u0456": "i",   # і → i
    # Cyrillic uppercase
    "\u0410": "A",   # А → A
    "\u0412": "B",   # В → B
    "\u0415": "E",   # Е → E
    "\u041a": "K",   # К → K
    "\u041c": "M",   # М → M
    "\u041d": "H",   # Н → H
    "\u041e": "O",   # О → O
    "\u0420": "P",   # Р → P
    "\u0421": "C",   # С → C
    "\u0422": "T",   # Т → T
    "\u0425": "X",   # Х → X
    "\u042a": "",    # Ъ (hard sign - remove)
    # Greek lookalikes
    "\u03bf": "o",   # ο → o
    "\u03b1": "a",   # α → a
    "\u03b5": "e",   # ε → e
    "\u03bd": "v",   # ν → v
    # Fullwidth ASCII (common in East Asian text)
    **{chr(0xFF01 + i): chr(0x21 + i) for i in range(94)},
}

_HOMOGLYPH_PATTERN = re.compile(
    "[" + re.escape("".join(_HOMOGLYPH_MAP.keys())) + "]"
)


def _normalize_for_comparison(name: str) -> str:
    """
    Normalize a name for fuzzy comparison.
    - NFKD decomposition
    - Replace homoglyph characters
    - Lower-case
    - Strip non-alphanumeric
    """
    # Apply homoglyph substitution
    result = ""
    for ch in name:
        result += _HOMOGLYPH_MAP.get(ch, ch)
    # NFKD → strip combining marks
    result = unicodedata.normalize("NFKD", result)
    result = "".join(c for c in result if not unicodedata.combining(c))
    return result.lower().strip()


def _contains_homoglyphs(name: str) -> list[tuple[str, str]]:
    """
    Return list of (original_char, ascii_equivalent) pairs for any
    homoglyph characters found in name.
    """
    return [
        (ch, _HOMOGLYPH_MAP[ch])
        for ch in name
        if ch in _HOMOGLYPH_MAP
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Levenshtein distance (pure Python, no external dependency)
# ──────────────────────────────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    """
    Compute Levenshtein edit distance between two strings.

    Uses the optimized two-row DP approach.  Fast enough for checking one
    name against a list of ~1000 artists.  For 10K+ artist lists, replace
    with rapidfuzz.distance.Levenshtein.distance() for C-speed.
    """
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


# ──────────────────────────────────────────────────────────────────────────────
# Keyword lists
# ──────────────────────────────────────────────────────────────────────────────

_FUNCTIONAL_KEYWORDS: frozenset[str] = frozenset({
    # Sleep
    "sleep", "sleeping", "insomnia", "bedtime", "lullaby", "deep sleep",
    "baby sleep", "sleep music", "sleep sounds",
    # Study / focus
    "study", "studying", "focus", "concentration", "exam", "study music",
    "brain music", "focus music", "deep work", "productivity",
    # Meditation / wellness
    "meditation", "meditate", "mindfulness", "zen", "chakra", "yoga",
    "healing", "therapy", "spiritual", "mantra", "binaural", "solfeggio",
    # Nature / ambient
    "white noise", "brown noise", "pink noise", "rain sounds", "rain music",
    "ocean waves", "forest sounds", "nature sounds", "thunderstorm",
    "fireplace", "café sounds", "coffee shop",
    # Relaxation
    "relaxation", "relax", "calm", "calming", "stress relief", "anxiety relief",
    "peaceful", "serenity", "tranquil",
    # ASMR
    "asmr", "whisper", "tapping",
    # Background
    "background music", "work music", "library music", "study lofi",
    "lofi beats", "chill beats",
})

_GENERIC_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^track\s*\d+$", re.IGNORECASE),
    re.compile(r"^untitled\s*\d*$", re.IGNORECASE),
    re.compile(r"^new\s+song\s*\d*$", re.IGNORECASE),
    re.compile(r"^demo\s*\d*$", re.IGNORECASE),
    re.compile(r"^recording\s*\d*$", re.IGNORECASE),
    re.compile(r"^test\s+track\s*\d*$", re.IGNORECASE),
    re.compile(r"^\d+$"),                               # Just a number
    re.compile(r"^song\s*\d*$", re.IGNORECASE),
    re.compile(r"^audio\s*\d*$", re.IGNORECASE),
    re.compile(r"^instrumental\s*\d+$", re.IGNORECASE),
    re.compile(r"^unknown$", re.IGNORECASE),
]

_KNOWN_AI_TOOLS: frozenset[str] = frozenset({
    "suno", "udio", "amper", "aiva", "mubert", "loudly",
    "boomy", "soundraw", "beatoven", "ecrett", "soundful",
    "ai music", "ai generated", "ai composed", "artificial intelligence",
    "generated by", "created by ai",
})

# ──────────────────────────────────────────────────────────────────────────────
# Signal / YAML loading
# ──────────────────────────────────────────────────────────────────────────────

_SIGNALS_YAML = Path(__file__).parent.parent.parent / "rules" / "fraud" / "signals.yaml"
_ARTISTS_FILE = Path(__file__).parent / "data" / "top_artists.txt"


def _load_signal_definitions(yaml_path: Path) -> dict[str, SignalDefinition]:
    """Load fraud signal definitions from YAML."""
    signals: dict[str, SignalDefinition] = {}
    if not yaml_path.exists():
        logger.warning("signals.yaml not found at %s — using empty definitions", yaml_path)
        return signals

    with yaml_path.open() as fh:
        doc = yaml.safe_load(fh)

    for entry in doc.get("signals", []):
        sig_id = entry["id"]
        signals[sig_id] = SignalDefinition(
            id=sig_id,
            name=entry.get("name", sig_id),
            category=entry.get("category", ""),
            severity=entry.get("severity", "warning"),
            advisory=entry.get("advisory", True),
            description=entry.get("description", ""),
            resolution=entry.get("resolution", "Contact support to resolve this flag."),
        )
    return signals


def _load_known_artists(artists_file: Path) -> list[str]:
    """Load known artist names, stripping comments and blank lines."""
    if not artists_file.exists():
        return []
    artists: list[str] = []
    for line in artists_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            artists.append(line)
    return artists


# ──────────────────────────────────────────────────────────────────────────────
# ReleaseMetadata import — avoid circular dependency
# ──────────────────────────────────────────────────────────────────────────────

def _import_metadata():
    from services.metadata.rules_engine import ReleaseMetadata
    return ReleaseMetadata


# ──────────────────────────────────────────────────────────────────────────────
# FraudScreener
# ──────────────────────────────────────────────────────────────────────────────

class FraudScreener:
    """
    Pre-screening service that evaluates release metadata for fraud signals.

    Instantiate once at application startup (heavy resources loaded in __init__).

    Usage::

        screener = FraudScreener()

        # With velocity data pre-fetched from DB:
        velocity = VelocityContext(releases_by_artist_30d=8, releases_by_org_7d=3)
        signals = screener.screen(metadata, org_id="abc", velocity=velocity)

        # Without DB (velocity + duplicate checks return 0 signals):
        signals = screener.screen(metadata, org_id="abc")
    """

    # Velocity thresholds
    ARTIST_VELOCITY_THRESHOLD_30D = 5
    ORG_VELOCITY_THRESHOLD_7D = 20

    # Functional music spam: fire if this many indicators are present
    FUNCTIONAL_SPAM_MIN_INDICATORS = 2

    # Artist similarity: flag if Levenshtein distance ≤ this value
    ARTIST_SIMILARITY_MAX_DISTANCE = 2

    def __init__(
        self,
        signals_yaml: Path | None = None,
        artists_file: Path | None = None,
    ) -> None:
        self._definitions: dict[str, SignalDefinition] = _load_signal_definitions(
            signals_yaml or _SIGNALS_YAML
        )
        self._known_artists: list[str] = _load_known_artists(
            artists_file or _ARTISTS_FILE
        )
        # Pre-normalise known artists for faster comparison
        self._known_artists_normalised: list[tuple[str, str]] = [
            (name, _normalize_for_comparison(name)) for name in self._known_artists
        ]
        logger.info(
            "FraudScreener loaded %d signal definitions, %d known artists",
            len(self._definitions),
            len(self._known_artists),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def screen(
        self,
        metadata: Any,           # ReleaseMetadata (lazy import avoids circular deps)
        org_id: str,
        velocity: VelocityContext | None = None,
        known_isrcs: dict[str, str] | None = None,
    ) -> list[FraudSignal]:
        """
        Run all fraud checks against the provided metadata.

        Args:
            metadata:      ReleaseMetadata instance.
            org_id:        Organization UUID string (for velocity checks).
            velocity:      Pre-fetched velocity counts from the pipeline task.
                           If None, velocity checks are skipped.
            known_isrcs:   Mapping of ISRC → release_id for ISRCs that already
                           exist in the corpus.  If None, duplicate check is skipped.

        Returns:
            List of FraudSignal objects (may be empty for clean releases).
        """
        signals: list[FraudSignal] = []

        signals.extend(self._check_functional_music_spam(metadata))
        signals.extend(self._check_short_track_duration(metadata))
        signals.extend(self._check_artist_name_similarity(metadata))
        signals.extend(self._check_release_velocity(metadata, org_id, velocity))
        signals.extend(self._check_generic_titles(metadata))
        signals.extend(self._check_ai_generation_indicators(metadata))
        signals.extend(self._check_duplicate_patterns(metadata, known_isrcs))

        # Annotate all signals with advisory note for low-confidence ones
        for sig in signals:
            if sig.is_advisory:
                sig.details["note"] = (
                    "This is an advisory signal, not an automatic block. "
                    "The release will proceed to DSP validation while this flag "
                    "is under review."
                )

        return signals

    # ── Detection: functional music spam ─────────────────────────────────────

    def _check_functional_music_spam(self, metadata: Any) -> list[FraudSignal]:
        """
        Flag releases that match 2+ functional music spam indicators:
        1. Artist name contains functional keywords
        2. > 70% of track titles contain functional keywords
        3. > 20 tracks in the release (volume indicator)
        4. All tracks have the same duration ±2 seconds (AI loop signal)
        5. Track titles follow a formulaic numbered pattern
        """
        indicators: list[str] = []
        details: dict[str, Any] = {}

        artist_lower = metadata.artist.lower()
        title_lower = metadata.title.lower()

        # Indicator 1: artist name contains functional keywords
        artist_kw = [kw for kw in _FUNCTIONAL_KEYWORDS if kw in artist_lower]
        if artist_kw:
            indicators.append(f"artist name contains functional keyword(s): {', '.join(artist_kw[:3])}")
            details["artist_keywords"] = artist_kw

        # Indicator 2: release title contains functional keywords
        release_kw = [kw for kw in _FUNCTIONAL_KEYWORDS if kw in title_lower]
        if release_kw:
            indicators.append(f"release title contains functional keyword(s): {', '.join(release_kw[:3])}")
            details["release_keywords"] = release_kw

        # Indicator 3: track count
        tracks = metadata.tracks
        if len(tracks) > 20:
            indicators.append(f"unusually high track count: {len(tracks)} tracks")
            details["track_count"] = len(tracks)

        # Indicator 4: all tracks same duration ±2 seconds
        duration_signal = self._all_tracks_same_duration(tracks)
        if duration_signal:
            indicators.append(duration_signal)
            details["uniform_duration"] = True

        # Indicator 5: formulaic numbered titles (e.g. "Sleep Music 1", "Sleep Music 2")
        if len(tracks) >= 3:
            formulaic = self._count_formulaic_titles(tracks)
            if formulaic >= max(3, len(tracks) * 0.7):
                indicators.append(
                    f"{formulaic}/{len(tracks)} tracks have formulaic numbered titles"
                )
                details["formulaic_titles"] = formulaic

        if len(indicators) < self.FUNCTIONAL_SPAM_MIN_INDICATORS:
            return []

        # Confidence scales with indicator count
        confidence = "low" if len(indicators) == 2 else (
            "medium" if len(indicators) == 3 else "high"
        )
        defn = self._get_definition("fraud.functional_music_spam")
        return [
            FraudSignal(
                signal_id="fraud.functional_music_spam",
                confidence=confidence,
                explanation=(
                    f"Release '{metadata.title}' by '{metadata.artist}' triggered "
                    f"{len(indicators)} functional music spam indicators: "
                    + "; ".join(indicators) + "."
                ),
                resolution=defn.resolution,
                is_advisory=defn.advisory,
                severity=defn.severity,
                matched_value=metadata.artist,
                category=defn.category,
                details=details,
            )
        ]

    def _all_tracks_same_duration(self, tracks: list[dict]) -> str:
        """
        Return a description string if all tracks have ±2 s duration, else "".
        Also creates a separate signal if triggered.
        """
        if len(tracks) < 3:
            return ""
        durations_ms = [
            t.get("duration_ms") for t in tracks
            if t.get("duration_ms") and isinstance(t.get("duration_ms"), (int, float))
        ]
        if len(durations_ms) < 3:
            return ""
        min_ms = min(durations_ms)
        max_ms = max(durations_ms)
        if (max_ms - min_ms) <= 2000:   # ±2 seconds
            avg_s = int(sum(durations_ms) / len(durations_ms) / 1000)
            return f"all {len(durations_ms)} tracks have near-identical duration (~{avg_s}s)"
        return ""

    def _count_formulaic_titles(self, tracks: list[dict]) -> int:
        """Count tracks whose titles follow a '[prefix] [number]' pattern."""
        pattern = re.compile(r"^(.+?)\s+\d+\s*$")
        prefixes: dict[str, int] = {}
        for t in tracks:
            title = (t.get("title") or "").strip()
            m = pattern.match(title)
            if m:
                prefix = m.group(1).lower()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
        # Only count if multiple tracks share the same prefix
        return sum(v for v in prefixes.values() if v >= 2)

    # ── Detection: short track duration ──────────────────────────────────────

    SHORT_TRACK_THRESHOLD_S = 60  # DSPs flag tracks under 60 seconds

    def _check_short_track_duration(self, metadata: Any) -> list[FraudSignal]:
        """
        Flag releases containing tracks shorter than 60 seconds.
        Sub-60s tracks are a known music-spam signal: they game per-stream
        royalty payments by packing more 'plays' into a listening session.
        """
        tracks = metadata.tracks
        if not tracks:
            return []

        short_tracks: list[dict] = []
        for t in tracks:
            dur_s = t.get("duration_s")
            if dur_s is not None and isinstance(dur_s, (int, float)) and dur_s < self.SHORT_TRACK_THRESHOLD_S:
                short_tracks.append({
                    "title": t.get("title", "Unknown"),
                    "duration_s": dur_s,
                    "isrc": t.get("isrc", ""),
                })

        if not short_tracks:
            return []

        defn = self._get_definition("fraud.short_track_duration")
        titles = ", ".join(f"'{t['title']}' ({t['duration_s']}s)" for t in short_tracks[:3])
        return [
            FraudSignal(
                signal_id="fraud.short_track_duration",
                confidence="high",
                explanation=(
                    f"{len(short_tracks)} track(s) in this release are under "
                    f"{self.SHORT_TRACK_THRESHOLD_S} seconds: {titles}. "
                    "Sub-60s tracks are a music-spam signal associated with "
                    "stream-count manipulation and are frequently rejected by DSPs."
                ),
                resolution=defn.resolution,
                is_advisory=defn.advisory,
                severity=defn.severity,
                matched_value=titles,
                category=defn.category,
                details={"short_tracks": short_tracks, "threshold_s": self.SHORT_TRACK_THRESHOLD_S},
            )
        ]

    # ── Detection: artist name similarity & homoglyphs ────────────────────────

    def _check_artist_name_similarity(self, metadata: Any) -> list[FraudSignal]:
        """
        Check artist name against known artists using Levenshtein distance and
        Unicode homoglyph detection.
        """
        signals: list[FraudSignal] = []
        artist = metadata.artist.strip()
        if not artist:
            return []

        # --- Homoglyph check ---
        homoglyphs = _contains_homoglyphs(artist)
        if homoglyphs:
            artist_ascii = _normalize_for_comparison(artist)
            # Check if the ASCII-normalised version matches a known artist closely
            close_artist = self._find_close_artist(artist_ascii, max_distance=1)
            defn = self._get_definition("fraud.homoglyph_artist_name")
            explanation = (
                f"Artist name '{artist}' contains Unicode homoglyph characters "
                f"that visually mimic ASCII text: "
                + ", ".join(f"'{orig}' → '{asc}'" for orig, asc in homoglyphs[:5])
                + "."
            )
            if close_artist:
                explanation += (
                    f" After normalisation, the name closely resembles "
                    f"known artist '{close_artist}'."
                )
            signals.append(
                FraudSignal(
                    signal_id="fraud.homoglyph_artist_name",
                    confidence="high" if close_artist else "medium",
                    explanation=explanation,
                    resolution=defn.resolution,
                    is_advisory=defn.advisory,
                    severity=defn.severity,
                    matched_value=artist,
                    category=defn.category,
                    details={"homoglyphs": [(o, a) for o, a in homoglyphs[:10]]},
                )
            )

        # --- Levenshtein similarity check (only if no homoglyphs already block) ---
        # Use normalised form to avoid false positives from accents/punctuation
        artist_norm = _normalize_for_comparison(artist)
        close_match = self._find_close_artist(
            artist_norm, max_distance=self.ARTIST_SIMILARITY_MAX_DISTANCE
        )
        if close_match:
            norm_close = _normalize_for_comparison(close_match)
            # Skip if normalised forms are too different in length (avoids short-name noise)
            if abs(len(artist_norm) - len(norm_close)) <= 3:
                dist = _levenshtein(artist_norm, norm_close)
                confidence = "high" if dist <= 1 else "medium"
                defn = self._get_definition("fraud.artist_name_similarity")
                signals.append(
                    FraudSignal(
                        signal_id="fraud.artist_name_similarity",
                        confidence=confidence,
                        explanation=(
                            f"Artist name '{artist}' is very similar to known artist "
                            f"'{close_match}' (edit distance: {dist}). This may indicate "
                            f"an attempt to impersonate or benefit from the established "
                            f"artist's audience."
                        ),
                        resolution=defn.resolution,
                        is_advisory=defn.advisory,
                        severity=defn.severity,
                        matched_value=artist,
                        category=defn.category,
                        details={"similar_to": close_match, "edit_distance": dist},
                    )
                )

        return signals

    def _find_close_artist(self, normalised_name: str, max_distance: int) -> str | None:
        """
        Return the first known artist whose normalised name is within
        max_distance of normalised_name, or None.
        """
        for original, norm in self._known_artists_normalised:
            # Quick length pre-filter: if lengths differ by more than max_distance,
            # Levenshtein will always exceed max_distance — skip the full comparison.
            if abs(len(normalised_name) - len(norm)) > max_distance:
                continue
            if normalised_name == norm:
                return None      # Exact match = same artist, not impersonation
            dist = _levenshtein(normalised_name, norm)
            if dist <= max_distance:
                return original
        return None

    # ── Detection: release velocity ───────────────────────────────────────────

    def _check_release_velocity(
        self,
        metadata: Any,
        org_id: str,
        velocity: VelocityContext | None,
    ) -> list[FraudSignal]:
        """
        Flag unusually high release rates.

        velocity is pre-fetched by the pipeline task before calling screen().
        If None, the check is skipped (no signal emitted).
        """
        if velocity is None:
            return []

        signals: list[FraudSignal] = []

        # Per-artist velocity (30 days)
        if velocity.releases_by_artist_30d > self.ARTIST_VELOCITY_THRESHOLD_30D:
            count = velocity.releases_by_artist_30d
            confidence = "high" if count > self.ARTIST_VELOCITY_THRESHOLD_30D * 4 else "medium"
            defn = self._get_definition("fraud.high_release_velocity_artist")
            signals.append(
                FraudSignal(
                    signal_id="fraud.high_release_velocity_artist",
                    confidence=confidence,
                    explanation=(
                        f"Artist '{metadata.artist}' has submitted {count} releases in "
                        f"the last 30 days (threshold: {self.ARTIST_VELOCITY_THRESHOLD_30D}). "
                        f"High-volume automated submissions are a common indicator of "
                        f"streaming fraud operations."
                    ),
                    resolution=defn.resolution,
                    is_advisory=defn.advisory,
                    severity=defn.severity,
                    matched_value=metadata.artist,
                    category=defn.category,
                    details={
                        "releases_in_30d": count,
                        "threshold": self.ARTIST_VELOCITY_THRESHOLD_30D,
                    },
                )
            )

        # Per-org velocity (7 days)
        if velocity.releases_by_org_7d > self.ORG_VELOCITY_THRESHOLD_7D:
            count = velocity.releases_by_org_7d
            confidence = "high" if count > self.ORG_VELOCITY_THRESHOLD_7D * 3 else "medium"
            defn = self._get_definition("fraud.high_release_velocity_org")
            signals.append(
                FraudSignal(
                    signal_id="fraud.high_release_velocity_org",
                    confidence=confidence,
                    explanation=(
                        f"Organization {org_id!r} has submitted {count} releases in "
                        f"the last 7 days (threshold: {self.ORG_VELOCITY_THRESHOLD_7D}). "
                        f"A sudden spike in submission volume may indicate account "
                        f"compromise or a bulk spam campaign."
                    ),
                    resolution=defn.resolution,
                    is_advisory=defn.advisory,
                    severity=defn.severity,
                    matched_value=org_id,
                    category=defn.category,
                    details={
                        "releases_in_7d": count,
                        "threshold": self.ORG_VELOCITY_THRESHOLD_7D,
                        "org_id": org_id,
                    },
                )
            )

        return signals

    # ── Detection: generic titles ─────────────────────────────────────────────

    def _check_generic_titles(self, metadata: Any) -> list[FraudSignal]:
        """Flag releases where >30% of tracks have placeholder/generic titles."""
        tracks = metadata.tracks
        if not tracks:
            return []

        generic_titles: list[str] = []
        for t in tracks:
            title = (t.get("title") or "").strip()
            if any(p.match(title) for p in _GENERIC_TITLE_PATTERNS):
                generic_titles.append(title)

        if not generic_titles:
            return []

        ratio = len(generic_titles) / len(tracks)
        if ratio < 0.3:
            return []

        confidence = "high" if ratio > 0.7 else "medium"
        defn = self._get_definition("fraud.generic_track_titles")
        return [
            FraudSignal(
                signal_id="fraud.generic_track_titles",
                confidence=confidence,
                explanation=(
                    f"{len(generic_titles)} of {len(tracks)} tracks "
                    f"({int(ratio * 100)}%) have generic or placeholder titles: "
                    + ", ".join(f"'{t}'" for t in generic_titles[:5])
                    + ("..." if len(generic_titles) > 5 else "")
                    + ". Releases with incomplete metadata are frequently rejected by "
                    f"DSP editorial teams."
                ),
                resolution=defn.resolution,
                is_advisory=defn.advisory,
                severity=defn.severity,
                matched_value=", ".join(generic_titles[:3]),
                category=defn.category,
                details={"generic_titles": generic_titles, "ratio": round(ratio, 2)},
            )
        ]

    # ── Detection: AI generation indicators ──────────────────────────────────

    def _check_ai_generation_indicators(self, metadata: Any) -> list[FraudSignal]:
        """
        Flag releases showing multiple AI-generation signals:
        1. No composer credits
        2. Publisher name matches known AI tool names
        3. All track titles follow a '[keyword] [number]' pattern
        4. Large track count + no composer + no ISWC
        5. Artist name mentions AI tools
        """
        indicators: list[str] = []
        details: dict[str, Any] = {}

        # Indicator 1: missing composer credits
        composers = metadata.composers or []
        has_composers = bool(composers) or bool(
            any(t.get("composer") for t in metadata.tracks)
        )
        if not has_composers:
            indicators.append("no composer or lyricist credits provided")
            details["missing_composers"] = True

        # Indicator 2: publisher name matches AI tools
        publisher_lower = (metadata.publisher or "").lower()
        matched_tools = [
            tool for tool in _KNOWN_AI_TOOLS
            if tool in publisher_lower
        ]
        artist_lower = metadata.artist.lower()
        title_lower = metadata.title.lower()
        for field_val in (artist_lower, title_lower):
            matched_tools.extend(
                tool for tool in _KNOWN_AI_TOOLS if tool in field_val
            )
        if matched_tools:
            unique_tools = list(dict.fromkeys(matched_tools))[:3]
            indicators.append(
                f"name/publisher references known AI music tool(s): {', '.join(unique_tools)}"
            )
            details["ai_tool_references"] = unique_tools

        # Indicator 3: formulaic numbered titles across ALL tracks
        tracks = metadata.tracks
        if len(tracks) >= 3:
            formulaic = self._count_formulaic_titles(tracks)
            if formulaic >= len(tracks) * 0.8:
                indicators.append(
                    f"{formulaic}/{len(tracks)} tracks follow formulaic '[name] [N]' titling"
                )
                details["formulaic_ratio"] = round(formulaic / len(tracks), 2)

        # Indicator 4: missing ISWC + no composers + large release
        if not has_composers and not metadata.iswc and len(tracks) >= 5:
            indicators.append(
                "no ISWC, no composer credits, and multiple tracks — "
                "composition rights cannot be verified"
            )
            details["unverifiable_composition"] = True

        # Indicator 5: all tracks uniform duration (already checked in spam, but also
        # a standalone AI indicator for non-spam releases)
        dur_signal = self._all_tracks_same_duration(tracks)
        if dur_signal and len(tracks) >= 5:
            indicators.append(dur_signal)

        if len(indicators) < 2:
            return []

        confidence = "low" if len(indicators) == 2 else (
            "medium" if len(indicators) == 3 else "high"
        )
        defn = self._get_definition("fraud.ai_generation_suspected")
        return [
            FraudSignal(
                signal_id="fraud.ai_generation_suspected",
                confidence=confidence,
                explanation=(
                    f"Release '{metadata.title}' shows {len(indicators)} indicators "
                    f"consistent with AI-generated audio: "
                    + "; ".join(indicators) + ". "
                    f"DSP AI content policies require disclosure of AI-generated material."
                ),
                resolution=defn.resolution,
                is_advisory=defn.advisory,
                severity=defn.severity,
                matched_value=metadata.artist,
                category=defn.category,
                details=details,
            )
        ]

    # ── Detection: duplicate ISRCs ────────────────────────────────────────────

    def _check_duplicate_patterns(
        self,
        metadata: Any,
        known_isrcs: dict[str, str] | None,
    ) -> list[FraudSignal]:
        """
        Flag ISRCs that are already associated with a different release.

        known_isrcs: {isrc: existing_release_id} — pre-fetched by the pipeline
        task from the tracks table.  If None, this check is skipped.
        """
        if known_isrcs is None:
            return []

        current_release_id = str(getattr(metadata, "release_id", "")) or ""
        conflicting: list[dict] = []

        for isrc in metadata.isrc_list:
            existing_release_id = known_isrcs.get(isrc)
            if existing_release_id and existing_release_id != current_release_id:
                conflicting.append({
                    "isrc": isrc,
                    "existing_release_id": existing_release_id,
                })

        if not conflicting:
            return []

        defn = self._get_definition("fraud.duplicate_isrc")
        isrc_list_str = ", ".join(c["isrc"] for c in conflicting[:5])
        return [
            FraudSignal(
                signal_id="fraud.duplicate_isrc",
                confidence="high",   # ISRC conflict is deterministic, always high confidence
                explanation=(
                    f"{len(conflicting)} ISRC(s) in this release are already associated "
                    f"with a different release in the corpus: {isrc_list_str}. "
                    f"ISRC reuse across different recordings is a critical error that "
                    f"corrupts royalty attribution and blocks DSP ingestion."
                ),
                resolution=defn.resolution,
                is_advisory=defn.advisory,
                severity=defn.severity,
                matched_value=isrc_list_str,
                category=defn.category,
                details={"conflicting_isrcs": conflicting},
            )
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_definition(self, signal_id: str) -> SignalDefinition:
        """Return definition by id, falling back to a safe default."""
        if signal_id in self._definitions:
            return self._definitions[signal_id]
        return SignalDefinition(
            id=signal_id,
            name=signal_id,
            category="unknown",
            severity="warning",
            advisory=True,
            description="",
            resolution="Contact support to resolve this flag.",
        )
