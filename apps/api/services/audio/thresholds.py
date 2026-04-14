"""
DSP-specific audio quality thresholds.

All numeric values follow these sign conventions:
  loudness_target_lufs   — negative float (e.g. -14.0)
  loudness_warn_range    — (low, high) both negative (e.g. (-18.0, -9.0))
  true_peak_max_dbtp     — negative float (e.g. -1.0)
  min_duration_seconds   — positive int (for monetization eligibility)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DSPThreshold:
    """Audio quality thresholds for a single DSP."""
    name: str

    # Accepted lossless formats (lowercase)
    accepted_formats: frozenset[str] = field(default_factory=frozenset)

    # Minimum technical requirements
    min_bit_depth: int = 16        # bits
    min_sample_rate: int = 44100   # Hz

    # Preferred/recommended technical specs
    preferred_bit_depth: int = 24
    preferred_sample_rates: frozenset[int] = field(default_factory=frozenset)

    # Loudness — EBU R128
    loudness_target_lufs: float = -14.0
    loudness_warn_low: float = -18.0    # below this = too quiet
    loudness_warn_high: float = -9.0    # above this = too loud (will be attenuated)

    # True peak ceiling
    true_peak_max_dbtp: float = -1.0

    # Lossy format preferred bitrate
    preferred_bitrate_kbps: int | None = None

    # Minimum track duration for monetization (TikTok-specific)
    min_duration_seconds: int | None = None

    # Spatial audio
    supports_dolby_atmos: bool = False
    atmos_target_lufs: float | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Per-DSP threshold definitions
# ──────────────────────────────────────────────────────────────────────────────

SPOTIFY = DSPThreshold(
    name="spotify",
    # Accepts WAV / FLAC / MP3 / OGG / AAC
    accepted_formats=frozenset({"wav", "flac", "mp3", "ogg", "aac", "m4a"}),
    min_bit_depth=16,
    min_sample_rate=44100,
    preferred_bit_depth=24,
    preferred_sample_rates=frozenset({44100, 48000}),
    loudness_target_lufs=-14.0,
    loudness_warn_low=-18.0,
    loudness_warn_high=-9.0,
    true_peak_max_dbtp=-1.0,
    preferred_bitrate_kbps=320,
)

APPLE = DSPThreshold(
    name="apple",
    # Prefers WAV / AIFF / ALAC; also accepts FLAC
    accepted_formats=frozenset({"wav", "aiff", "aif", "alac", "flac", "m4a"}),
    min_bit_depth=16,
    min_sample_rate=44100,
    preferred_bit_depth=24,
    preferred_sample_rates=frozenset({44100, 48000, 88200, 96000, 192000}),
    loudness_target_lufs=-16.0,
    loudness_warn_low=-20.0,
    loudness_warn_high=-12.0,
    true_peak_max_dbtp=-1.0,
    supports_dolby_atmos=True,
    atmos_target_lufs=-18.0,
)

YOUTUBE = DSPThreshold(
    name="youtube",
    # Accepts MP3 320 kbps OR WAV 16-bit 48 kHz
    accepted_formats=frozenset({"wav", "flac", "mp3", "aac", "m4a", "ogg"}),
    min_bit_depth=16,
    min_sample_rate=48000,     # preferred; 44100 also accepted
    preferred_bit_depth=24,
    preferred_sample_rates=frozenset({48000, 44100}),
    loudness_target_lufs=-14.0,
    loudness_warn_low=-18.0,
    loudness_warn_high=-10.0,
    true_peak_max_dbtp=-1.0,
    preferred_bitrate_kbps=320,
)

AMAZON = DSPThreshold(
    name="amazon",
    # FLAC 24-bit 96 kHz preferred for HD; min 16-bit 44.1 kHz
    accepted_formats=frozenset({"wav", "flac", "aiff", "aif", "alac", "m4a"}),
    min_bit_depth=16,
    min_sample_rate=44100,
    preferred_bit_depth=24,
    preferred_sample_rates=frozenset({44100, 48000, 88200, 96000, 192000}),
    loudness_target_lufs=-14.0,
    loudness_warn_low=-18.0,
    loudness_warn_high=-9.0,
    true_peak_max_dbtp=-1.0,
)

TIKTOK = DSPThreshold(
    name="tiktok",
    # MP3 320 kbps or WAV; minimum 60 seconds for monetization
    accepted_formats=frozenset({"wav", "mp3", "flac", "aac", "m4a", "ogg"}),
    min_bit_depth=16,
    min_sample_rate=44100,
    preferred_bit_depth=24,
    preferred_sample_rates=frozenset({44100, 48000}),
    loudness_target_lufs=-14.0,
    loudness_warn_low=-18.0,
    loudness_warn_high=-10.0,
    true_peak_max_dbtp=-1.0,
    preferred_bitrate_kbps=320,
    min_duration_seconds=60,
)

# Registry: dsp_slug → threshold
DSP_THRESHOLDS: dict[str, DSPThreshold] = {
    "spotify": SPOTIFY,
    "apple":   APPLE,
    "youtube": YOUTUBE,
    "amazon":  AMAZON,
    "tiktok":  TIKTOK,
}


def check_against_threshold(
    result: "AudioAnalysisResult",  # noqa: F821 (forward ref, imported at call site)
    threshold: DSPThreshold,
) -> list[dict]:
    """
    Compare an AudioAnalysisResult against a DSPThreshold.

    Returns a list of finding dicts:
      {"rule_id", "severity", "message", "fix_hint", "actual_value"}
    """
    findings: list[dict] = []
    dsp = threshold.name

    # Format
    if (
        result.format
        and threshold.accepted_formats
        and result.format.lower() not in threshold.accepted_formats
    ):
        findings.append({
            "rule_id": f"{dsp}.audio.format_not_accepted",
            "severity": "critical",
            "message": (
                f"Audio format '{result.format}' is not accepted by {dsp.title()}. "
                f"Accepted: {', '.join(sorted(threshold.accepted_formats))}."
            ),
            "fix_hint": f"Convert to a supported format: {', '.join(sorted(threshold.accepted_formats))}.",
            "actual_value": result.format,
        })

    # Sample rate
    if result.sample_rate and result.sample_rate < threshold.min_sample_rate:
        findings.append({
            "rule_id": f"{dsp}.audio.sample_rate_too_low",
            "severity": "critical",
            "message": (
                f"Sample rate {result.sample_rate} Hz is below the {dsp.title()} minimum "
                f"of {threshold.min_sample_rate} Hz."
            ),
            "fix_hint": f"Re-export at {threshold.min_sample_rate} Hz or higher.",
            "actual_value": str(result.sample_rate),
        })
    elif (
        result.sample_rate
        and threshold.preferred_sample_rates
        and result.sample_rate not in threshold.preferred_sample_rates
    ):
        findings.append({
            "rule_id": f"{dsp}.audio.sample_rate_not_preferred",
            "severity": "info",
            "message": (
                f"Sample rate {result.sample_rate} Hz is not a preferred rate for "
                f"{dsp.title()}. Preferred: {sorted(threshold.preferred_sample_rates)}."
            ),
            "fix_hint": f"Re-export at a preferred rate: {sorted(threshold.preferred_sample_rates)}.",
            "actual_value": str(result.sample_rate),
        })

    # Bit depth
    if result.bit_depth and result.bit_depth < threshold.min_bit_depth:
        findings.append({
            "rule_id": f"{dsp}.audio.bit_depth_too_low",
            "severity": "critical",
            "message": (
                f"Bit depth {result.bit_depth}-bit is below the {dsp.title()} minimum "
                f"of {threshold.min_bit_depth}-bit."
            ),
            "fix_hint": f"Re-export at {threshold.min_bit_depth}-bit or higher.",
            "actual_value": str(result.bit_depth),
        })

    # True peak
    if (
        result.true_peak_dbtp is not None
        and result.true_peak_dbtp != 0.0
        and result.true_peak_dbtp > threshold.true_peak_max_dbtp
    ):
        findings.append({
            "rule_id": f"{dsp}.audio.true_peak_exceeded",
            "severity": "critical",
            "message": (
                f"True peak {result.true_peak_dbtp:.2f} dBTP exceeds {dsp.title()} "
                f"ceiling of {threshold.true_peak_max_dbtp:.1f} dBTP."
            ),
            "fix_hint": f"Apply true-peak limiting to {threshold.true_peak_max_dbtp:.1f} dBTP.",
            "actual_value": f"{result.true_peak_dbtp:.2f} dBTP",
        })

    # Loudness
    if result.integrated_lufs is not None and result.integrated_lufs != 0.0:
        lufs = result.integrated_lufs
        if lufs < threshold.loudness_warn_low:
            findings.append({
                "rule_id": f"{dsp}.audio.loudness_too_quiet",
                "severity": "warning",
                "message": (
                    f"Integrated loudness {lufs:.1f} LUFS is below the {dsp.title()} "
                    f"warning threshold ({threshold.loudness_warn_low:.1f} LUFS). "
                    f"The platform will boost this track, potentially increasing noise."
                ),
                "fix_hint": f"Re-master targeting {threshold.loudness_target_lufs:.1f} LUFS integrated.",
                "actual_value": f"{lufs:.1f} LUFS",
            })
        elif lufs > threshold.loudness_warn_high:
            findings.append({
                "rule_id": f"{dsp}.audio.loudness_too_loud",
                "severity": "warning",
                "message": (
                    f"Integrated loudness {lufs:.1f} LUFS is above the {dsp.title()} "
                    f"warning threshold ({threshold.loudness_warn_high:.1f} LUFS). "
                    f"The platform will attenuate this track, degrading dynamic range."
                ),
                "fix_hint": f"Re-master targeting {threshold.loudness_target_lufs:.1f} LUFS integrated.",
                "actual_value": f"{lufs:.1f} LUFS",
            })

    # Duration (TikTok monetization minimum)
    if (
        threshold.min_duration_seconds
        and result.duration_seconds
        and result.duration_seconds < threshold.min_duration_seconds
    ):
        findings.append({
            "rule_id": f"{dsp}.audio.duration_too_short",
            "severity": "warning",
            "message": (
                f"Track duration {result.duration_seconds:.1f}s is below the {dsp.title()} "
                f"monetization minimum of {threshold.min_duration_seconds}s."
            ),
            "fix_hint": (
                f"Ensure the track is at least {threshold.min_duration_seconds}s long "
                f"to qualify for {dsp.title()} monetization."
            ),
            "actual_value": f"{result.duration_seconds:.1f}s",
        })

    return findings
