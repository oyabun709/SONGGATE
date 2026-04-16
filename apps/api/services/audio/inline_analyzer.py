"""
Inline audio analysis — no ffmpeg, no Celery, no Redis.

Designed for Vercel serverless: uses only pure-Python or pre-compiled
wheel dependencies that are already in requirements.txt.

Analysis pipeline (per track URL)
──────────────────────────────────
1. Download audio file via httpx (streaming, 50 MB cap)
2. mutagen  → format, codec, sample_rate, bit_depth, channels, duration
3. soundfile + pyloudnorm → integrated LUFS + LRA  (WAV / FLAC / AIFF only)
   lossy formats (MP3, AAC, OGG, …) skip LUFS — noted in warnings
4. Clipping estimate: if true_peak > -1 dBTP (from pyloudnorm)
5. Cleanup temp file

Dependencies (all in requirements.txt):
  mutagen>=1.47     — pure Python, reads all common audio metadata
  soundfile>=0.12   — reads PCM audio for lossless formats
  pyloudnorm>=0.1   — EBU R128 LUFS measurement
  numpy>=1.26       — required by pyloudnorm
  httpx>=0.28       — async HTTP download

Returns: list[ScanResult] ready to be persisted by the orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from models.scan_result import ScanResult, ResultStatus
from services.audio.thresholds import DSP_THRESHOLDS, check_against_threshold
from services.audio.analyzer import AudioAnalysisResult

logger = logging.getLogger(__name__)

# Max file size to download (50 MB)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# Lossless formats soundfile can decode to PCM for LUFS measurement
_LOSSLESS_FORMATS = {"wav", "flac", "aiff", "aif", "alac"}


class InlineAudioAnalyzer:
    """
    Download and analyze a single audio file synchronously (blocking).
    Call from an executor thread or async wrapper.
    """

    def analyze_from_bytes(
        self,
        audio_bytes: bytes,
        audio_url: str,
        track_id: str,
    ) -> AudioAnalysisResult:
        """
        Blocking analysis of pre-downloaded audio bytes.
        Designed to run in loop.run_in_executor() — no network I/O here.
        """
        import io

        result = AudioAnalysisResult(track_id=track_id, audio_url=audio_url)
        result.file_size_bytes = len(audio_bytes)
        suffix = _url_extension(audio_url)
        buf = io.BytesIO(audio_bytes)

        # ── Step 1: mutagen — format metadata (needs a named file) ───────────
        tmp_path: Path | None = None
        try:
            fd, tmp_str = tempfile.mkstemp(
                prefix=f"sg-audio-{uuid.uuid4().hex[:8]}-", suffix=suffix
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(fd, "wb") as fh:
                fh.write(audio_bytes)

            try:
                import mutagen
                mf = mutagen.File(str(tmp_path), easy=False)
                if mf is not None:
                    _extract_mutagen_metadata(mf, tmp_path, result)
                else:
                    result.warnings.append("mutagen could not identify audio format.")
                    _guess_format_from_url(audio_url, suffix, result)
            except Exception as exc:
                result.warnings.append(f"mutagen error: {exc}")
                _guess_format_from_url(audio_url, suffix, result)
        except OSError as exc:
            result.warnings.append(f"Temp file unavailable ({exc}): using URL extension for format.")
            _guess_format_from_url(audio_url, suffix, result)
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        # ── Step 2: LUFS via soundfile + pyloudnorm (lossless, from memory) ──
        if result.format in _LOSSLESS_FORMATS:
            buf.seek(0)
            _measure_lufs_from_buffer(buf, result)
        else:
            result.warnings.append(
                f"LUFS skipped for lossy format '{result.format or 'unknown'}' "
                "(ffmpeg not available in serverless)."
            )

        return result


def _extract_mutagen_metadata(mf, path: Path, result: AudioAnalysisResult) -> None:
    """Pull technical metadata out of a mutagen FileType object."""
    info = getattr(mf, "info", None)
    if info is None:
        _guess_format_from_extension(path, result)
        return

    result.duration_seconds = getattr(info, "length", None)
    result.sample_rate = getattr(info, "sample_rate", None)
    result.channels = getattr(info, "channels", None)
    result.bitrate_kbps = _to_kbps(getattr(info, "bitrate", None))

    # Bit depth — only present for lossless formats
    result.bit_depth = getattr(info, "bits_per_sample", None) or None

    # Derive format + codec from class name
    cls = type(mf).__name__.lower()
    fmt, codec = _cls_to_format_codec(cls, path)
    result.format = fmt
    result.codec = codec


def _cls_to_format_codec(cls: str, path: Path) -> tuple[str | None, str | None]:
    """Map mutagen class name to (format, codec)."""
    mapping = {
        "flac":      ("flac",  "flac"),
        "wave":      ("wav",   "pcm"),
        "aiff":      ("aiff",  "pcm"),
        "aif":       ("aiff",  "pcm"),
        "mp3":       ("mp3",   "mp3"),
        "mp4":       ("m4a",   "aac"),
        "aac":       ("aac",   "aac"),
        "oggvorbis": ("ogg",   "vorbis"),
        "oggopus":   ("opus",  "opus"),
        "wavpack":   ("wavpack","wavpack"),
        "asf":       ("wma",   "wma"),
        "monkeysaudio": ("ape","ape"),
    }
    for key, (fmt, codec) in mapping.items():
        if key in cls:
            return fmt, codec
    # Fall back to file extension
    return _ext_to_format(path.suffix.lower().lstrip(".")), None


def _ext_to_format(ext: str) -> str | None:
    return {
        "wav": "wav", "wave": "wav",
        "flac": "flac",
        "mp3": "mp3",
        "m4a": "m4a", "mp4": "m4a",
        "aac": "aac",
        "aiff": "aiff", "aif": "aiff",
        "ogg": "ogg",
        "opus": "opus",
        "alac": "alac",
        "wma": "wma",
    }.get(ext)


def _guess_format_from_extension(path: Path, result: AudioAnalysisResult) -> None:
    ext = path.suffix.lower().lstrip(".")
    result.format = _ext_to_format(ext)
    if result.format is None:
        result.warnings.append(f"Unknown audio format (extension: '{ext}').")


def _guess_format_from_url(url: str, suffix: str, result: AudioAnalysisResult) -> None:
    """Guess format from URL extension when temp file can't be created."""
    ext = suffix.lstrip(".").lower()
    result.format = _ext_to_format(ext)
    if result.format is None:
        result.warnings.append(f"Unknown audio format from URL extension '{ext}'.")


def _measure_lufs(path: Path, result: AudioAnalysisResult) -> None:
    """Measure LUFS from a file path."""
    import io
    with path.open("rb") as f:
        _measure_lufs_from_buffer(io.BytesIO(f.read()), result)


def _measure_lufs_from_buffer(buf, result: AudioAnalysisResult) -> None:
    """Measure integrated LUFS from a BytesIO buffer using soundfile + pyloudnorm."""
    try:
        import numpy as np
        import pyloudnorm as pyln
        import soundfile as sf
    except ImportError as exc:
        result.warnings.append(f"pyloudnorm/soundfile not available: {exc}")
        return

    try:
        buf.seek(0)
        data, rate = sf.read(buf, always_2d=True)
    except Exception as exc:
        result.warnings.append(f"soundfile read error: {exc}")
        return

    try:
        meter = pyln.Meter(rate)
        lufs = meter.integrated_loudness(data)
        if lufs == lufs:  # NaN check
            result.integrated_lufs = round(lufs, 2)
    except Exception as exc:
        result.warnings.append(f"pyloudnorm LUFS error: {exc}")

    try:
        meter = pyln.Meter(rate)
        lra = meter.loudness_range(data)
        if lra == lra:
            result.loudness_range_lu = round(lra, 2)
    except Exception:
        pass

    # True peak estimation via numpy max (approximation — not ITU-R BS.1770-4)
    try:
        peak_linear = float(np.abs(data).max())
        if peak_linear > 0:
            import math
            result.true_peak_dbtp = round(20 * math.log10(peak_linear), 2)
            result.is_clipping = result.true_peak_dbtp > -1.0
    except Exception:
        pass


async def _ensure_rule(db, rule_id: str, layer: str, severity: str) -> None:
    """Upsert a minimal Rule row (same logic as ScanOrchestrator._ensure_rule)."""
    from datetime import datetime, timezone
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from models.rule import Rule

    stmt = (
        pg_insert(Rule)
        .values(
            id=rule_id,
            layer=layer,
            severity=severity,
            title=rule_id.replace(".", " ").replace("_", " ").title(),
            category=layer,
            version="1.0.0",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(stmt)


def _url_extension(url: str) -> str:
    path = url.split("?")[0].rstrip("/")
    _, _, fname = path.rpartition("/")
    if "." in fname:
        ext = "." + fname.rsplit(".", 1)[-1].lower()
        if len(ext) <= 6:
            return ext
    return ".bin"


def _to_kbps(bitrate: int | float | None) -> int | None:
    if bitrate is None:
        return None
    try:
        kbps = int(bitrate) // 1000
        return kbps if kbps > 0 else None
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Async wrapper + ScanResult builder
# ──────────────────────────────────────────────────────────────────────────────

async def analyze_track_inline(
    audio_url: str,
    track_id: str,
    track_title: str,
    scan_id: str,
    dsps: list[str],
    db,
) -> list[ScanResult]:
    """
    Async entry point: downloads audio async, then runs CPU analysis in executor.
    Separating download (async) from analysis (sync/executor) avoids httpx
    EBUSY issues that occur when running httpx sync client in a thread on Vercel.
    """
    # ── Step 1: download in executor (urllib avoids httpx EBUSY on Vercel) ────
    def _download_bytes(url: str) -> bytes:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "songgate-audio/1.0"})
        buf = bytearray()
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"Audio file exceeds {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit"
                    )
        return bytes(buf)

    audio_bytes: bytes | None = None
    loop = asyncio.get_event_loop()
    try:
        audio_bytes = await asyncio.wait_for(
            loop.run_in_executor(None, _download_bytes, audio_url),
            timeout=90.0,
        )
        logger.info(
            "Audio downloaded for track %s: %d bytes (%s)",
            track_id, len(audio_bytes), audio_url.split("?")[0][-40:],
        )
    except asyncio.TimeoutError:
        logger.warning("Audio download timed out for track %s", track_id)
        return []
    except Exception as exc:
        logger.warning("Audio download failed for track %s: %s", track_id, exc)
        return []

    # ── Step 2: CPU-bound analysis in executor ────────────────────────────────
    analyzer = InlineAudioAnalyzer()

    try:
        analysis = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                analyzer.analyze_from_bytes,
                audio_bytes,
                audio_url,
                track_id,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Audio analysis timed out for track %s", track_id)
        return []
    except Exception as exc:
        logger.warning("Audio analysis error for track %s: %s", track_id, exc)
        return []

    if not analysis.succeeded and analysis.errors:
        logger.warning(
            "Audio analysis failed for track %s: %s", track_id, "; ".join(analysis.errors)
        )
        return []

    scan_uuid = uuid.UUID(scan_id)
    now = datetime.now(timezone.utc)
    results: list[ScanResult] = []

    # Collect findings across all requested DSPs
    seen_rule_ids: set[str] = set()
    for dsp_slug in dsps:
        threshold = DSP_THRESHOLDS.get(dsp_slug)
        if not threshold:
            continue
        findings = check_against_threshold(analysis, threshold)
        for f in findings:
            rule_id = f["rule_id"]
            # Deduplicate identical rule_id+dsp combos (e.g. same sample rate fail on 3 DSPs)
            dedup_key = f"{rule_id}:{f.get('actual_value','')}"
            if dedup_key in seen_rule_ids:
                continue
            seen_rule_ids.add(dedup_key)

            severity = f["severity"]
            status = ResultStatus.fail if severity == "critical" else ResultStatus.warn

            await _ensure_rule(db, rule_id, "audio", severity)

            results.append(ScanResult(
                id=uuid.uuid4(),
                scan_id=scan_uuid,
                layer="audio",
                rule_id=rule_id,
                severity=severity,
                status=status,
                message=f["message"],
                fix_hint=f.get("fix_hint"),
                actual_value=f.get("actual_value"),
                dsp_targets=[dsp_slug],
                metadata_={
                    "format": analysis.format,
                    "codec": analysis.codec,
                    "sample_rate": analysis.sample_rate,
                    "bit_depth": analysis.bit_depth,
                    "duration_seconds": analysis.duration_seconds,
                    "integrated_lufs": analysis.integrated_lufs,
                    "track_title": track_title,
                },
                created_at=now,
            ))

    # If analysis succeeded with no DSP violations, emit a pass-level info
    if analysis.succeeded and not results:
        await _ensure_rule(db, "audio.analysis.passed", "audio", "info")
        results.append(ScanResult(
            id=uuid.uuid4(),
            scan_id=scan_uuid,
            layer="audio",
            rule_id="audio.analysis.passed",
            severity="info",
            status=ResultStatus.warn,
            message=(
                f"Audio analysis passed — "
                f"format={analysis.format or '?'}, "
                f"sample_rate={analysis.sample_rate or '?'} Hz, "
                f"bit_depth={analysis.bit_depth or '?'}-bit"
                + (f", LUFS={analysis.integrated_lufs:.1f}" if analysis.integrated_lufs else "")
                + "."
            ),
            fix_hint=None,
            actual_value=None,
            dsp_targets=[],
            metadata_={
                "format": analysis.format,
                "codec": analysis.codec,
                "sample_rate": analysis.sample_rate,
                "bit_depth": analysis.bit_depth,
                "duration_seconds": analysis.duration_seconds,
                "integrated_lufs": analysis.integrated_lufs,
                "track_title": track_title,
            },
            created_at=now,
        ))

    return results
