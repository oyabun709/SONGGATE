"""
Audio quality analysis service.

Never import this in an API request handler — it does blocking I/O and CPU-bound
processing.  All entry points are Celery tasks in tasks/audio_analysis.py.

Analysis pipeline (per track)
──────────────────────────────
1. Download audio from S3 presigned URL to a /tmp UUID file
2. ffprobe  → format, codec, sample_rate, bit_depth, channels, duration, bitrate
3. ffmpeg loudnorm filter → integrated_lufs, true_peak_dbtp, loudness_range_lu
4. pyloudnorm (on PCM decode) → integrated_lufs cross-check + loudness_range_lu
5. pyacoustid → AcoustID fingerprint for deduplication
6. Clipping detection (true_peak > -1 dBTP)
7. Silence detection (leading/trailing silence via ffmpeg silencedetect)
8. Cleanup temp file (always, even on error)

Dependencies
────────────
System: ffmpeg ≥ 4.4, fpcalc (chromaprint, for acoustid)
Python: ffmpeg-python, soundfile, pyloudnorm, pyacoustid, numpy, httpx, boto3
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AudioAnalysisResult:
    """
    Full audio analysis result for one track file.

    Numeric fields default to None (not yet measured).
    ``errors`` collects non-fatal issues encountered during analysis;
    a non-empty errors list does not mean the analysis failed — partial
    results are returned and stored.
    """
    track_id: str
    audio_url: str

    # Technical metadata (from ffprobe)
    format: str | None = None          # e.g. "wav", "flac", "mp3"
    codec: str | None = None           # e.g. "pcm_s24le", "flac"
    sample_rate: int | None = None     # Hz
    bit_depth: int | None = None       # bits per sample (0 for lossy)
    channels: int | None = None        # 1 = mono, 2 = stereo
    duration_seconds: float | None = None
    bitrate_kbps: int | None = None    # overall bitrate (for lossy)
    file_size_bytes: int | None = None

    # EBU R128 loudness (from ffmpeg loudnorm filter, cross-checked with pyloudnorm)
    integrated_lufs: float | None = None   # integrated program loudness
    true_peak_dbtp: float | None = None    # true peak (dBTP)
    loudness_range_lu: float | None = None # LRA (LU)

    # Quality flags
    is_clipping: bool = False          # true_peak > -1 dBTP
    has_leading_silence: bool = False  # > 2s silence at start
    has_trailing_silence: bool = False # > 2s silence at end

    # AcoustID fingerprint
    acoustid_fingerprint: str | None = None
    acoustid_duration: float | None = None

    # Analysis metadata
    analysis_duration_seconds: float | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_lossy(self) -> bool:
        """True if the format is a lossy codec."""
        lossy_formats = {"mp3", "aac", "ogg", "opus", "m4a", "wma"}
        return (self.format or "").lower() in lossy_formats

    @property
    def succeeded(self) -> bool:
        """True if at least basic metadata was extracted."""
        return self.format is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSONB storage in Track.metadata_."""
        return {
            "format": self.format,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
            "bitrate_kbps": self.bitrate_kbps,
            "file_size_bytes": self.file_size_bytes,
            "integrated_lufs": self.integrated_lufs,
            "true_peak_dbtp": self.true_peak_dbtp,
            "loudness_range_lu": self.loudness_range_lu,
            "is_clipping": self.is_clipping,
            "has_leading_silence": self.has_leading_silence,
            "has_trailing_silence": self.has_trailing_silence,
            "acoustid_fingerprint": self.acoustid_fingerprint,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ──────────────────────────────────────────────────────────────────────────────
# AudioAnalyzer
# ──────────────────────────────────────────────────────────────────────────────

class AudioAnalyzer:
    """
    Analyze an audio file at a given URL and return an AudioAnalysisResult.

    All heavy work is blocking; call only from Celery workers.

    Usage::

        analyzer = AudioAnalyzer()
        result = analyzer.analyze(audio_url="s3://...", track_id="uuid")
    """

    #: Silence threshold for leading/trailing silence detection
    SILENCE_DB = -60.0
    SILENCE_MIN_DURATION = 2.0   # seconds

    def __init__(self) -> None:
        self._ffmpeg_path = _find_binary("ffmpeg")
        self._ffprobe_path = _find_binary("ffprobe")
        self._fpcalc_path = _find_binary("fpcalc")

        if not self._ffmpeg_path:
            logger.warning(
                "ffmpeg not found on PATH — audio analysis will be limited. "
                "Install ffmpeg: https://ffmpeg.org/download.html"
            )
        if not self._fpcalc_path:
            logger.warning(
                "fpcalc (chromaprint) not found — AcoustID fingerprinting disabled. "
                "Install chromaprint: https://acoustid.org/chromaprint"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, audio_url: str, track_id: str) -> AudioAnalysisResult:
        """
        Download audio from URL, run full analysis pipeline, return results.

        The temp file is always deleted in the finally block even on exception.

        Args:
            audio_url: Public or presigned S3 URL to the audio file.
            track_id:  Track UUID string (for result tagging only).

        Returns:
            AudioAnalysisResult — check .errors for non-fatal issues.
        """
        start = time.monotonic()
        result = AudioAnalysisResult(track_id=track_id, audio_url=audio_url)
        tmp_path: Path | None = None

        try:
            # Step 1: download to temp file
            tmp_path = self._download(audio_url, result)
            if tmp_path is None:
                return result   # download error already recorded

            # Step 2: ffprobe — technical metadata
            self._probe(tmp_path, result)

            if not self._ffmpeg_path:
                result.errors.append("ffmpeg not available — loudness analysis skipped")
                return result

            # Step 3: EBU R128 via ffmpeg loudnorm filter
            self._measure_loudness_ffmpeg(tmp_path, result)

            # Step 4: pyloudnorm cross-check (on PCM decode)
            self._measure_loudness_pyloudnorm(tmp_path, result)

            # Step 5: AcoustID fingerprint
            self._fingerprint(tmp_path, result)

            # Step 6: clipping detection
            if result.true_peak_dbtp is not None:
                result.is_clipping = self._check_clipping(result.true_peak_dbtp)

            # Step 7: silence detection
            self._detect_silence(tmp_path, result)

        except Exception as exc:
            logger.exception("Unexpected error analyzing track %s: %s", track_id, exc)
            result.errors.append(f"unexpected analysis error: {exc}")
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError as exc:
                    logger.warning("Could not delete temp file %s: %s", tmp_path, exc)
            result.analysis_duration_seconds = round(time.monotonic() - start, 3)

        return result

    def _check_clipping(self, true_peak: float) -> bool:
        """Return True if true peak exceeds the -1 dBTP ceiling."""
        return true_peak > -1.0

    # ── Step 1: download ──────────────────────────────────────────────────────

    def _download(self, url: str, result: AudioAnalysisResult) -> Path | None:
        """Download audio from URL to a temp file. Returns Path or None on error."""
        suffix = _url_suffix(url) or ".bin"
        tmp = Path(tempfile.mkdtemp()) / f"ropqa-audio-{uuid.uuid4()}{suffix}"

        try:
            if url.startswith("s3://") or "s3.amazonaws.com" in url or "s3." in url:
                return self._download_s3(url, tmp, result)
            else:
                return self._download_http(url, tmp, result)
        except Exception as exc:
            result.errors.append(f"download failed: {exc}")
            return None

    def _download_http(self, url: str, dest: Path, result: AudioAnalysisResult) -> Path | None:
        """Download via HTTPS using httpx (streaming)."""
        try:
            import httpx
        except ImportError:
            result.errors.append("httpx not installed — cannot download audio")
            return None

        try:
            with httpx.Client(follow_redirects=True, timeout=120) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    content_length = resp.headers.get("content-length")
                    if content_length:
                        result.file_size_bytes = int(content_length)
                    with dest.open("wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            fh.write(chunk)
        except Exception as exc:
            result.errors.append(f"HTTP download error: {exc}")
            return None

        if not result.file_size_bytes:
            result.file_size_bytes = dest.stat().st_size
        return dest

    def _download_s3(self, url: str, dest: Path, result: AudioAnalysisResult) -> Path | None:
        """Download from S3 using boto3 (handles presigned URLs too)."""
        # Presigned https URLs go through HTTP download
        if url.startswith("https://") or url.startswith("http://"):
            return self._download_http(url, dest, result)

        # s3://bucket/key format
        try:
            import boto3
            from config import settings
        except ImportError:
            result.errors.append("boto3 not available")
            return None

        try:
            s3_url = url[5:]  # strip "s3://"
            bucket, _, key = s3_url.partition("/")
            kwargs: dict[str, Any] = {}
            if settings.s3_endpoint_url:
                kwargs["endpoint_url"] = settings.s3_endpoint_url
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None,
                region_name=settings.aws_region,
                **kwargs,
            )
            s3.download_file(bucket, key, str(dest))
            result.file_size_bytes = dest.stat().st_size
            return dest
        except Exception as exc:
            result.errors.append(f"S3 download error: {exc}")
            return None

    # ── Step 2: ffprobe ───────────────────────────────────────────────────────

    def _probe(self, path: Path, result: AudioAnalysisResult) -> None:
        """Use ffprobe to extract technical metadata into result."""
        if not self._ffprobe_path:
            result.warnings.append("ffprobe not available — technical metadata not extracted")
            return

        cmd = [
            self._ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                result.errors.append(f"ffprobe error: {proc.stderr[:200]}")
                return

            probe = json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            result.errors.append("ffprobe timed out after 30s")
            return
        except (json.JSONDecodeError, OSError) as exc:
            result.errors.append(f"ffprobe parse error: {exc}")
            return

        # Format block
        fmt = probe.get("format", {})
        result.duration_seconds = _float_or_none(fmt.get("duration"))
        result.bitrate_kbps = _int_kbps(fmt.get("bit_rate"))
        result.format = _guess_format(fmt.get("format_name", ""), path)

        # Find audio stream
        for stream in probe.get("streams", []):
            if stream.get("codec_type") != "audio":
                continue
            result.codec = stream.get("codec_name")
            result.sample_rate = _int_or_none(stream.get("sample_rate"))
            result.channels = _int_or_none(stream.get("channels"))
            result.bit_depth = _extract_bit_depth(stream)
            # Prefer stream duration if format duration is missing
            if not result.duration_seconds:
                result.duration_seconds = _float_or_none(stream.get("duration"))
            break

    # ── Step 3: EBU R128 via ffmpeg loudnorm filter ───────────────────────────

    def _measure_loudness_ffmpeg(self, path: Path, result: AudioAnalysisResult) -> None:
        """
        Run ffmpeg's loudnorm filter in analysis mode to get:
          - Integrated loudness (LUFS)
          - True peak (dBTP)
          - Loudness range (LU)
        """
        cmd = [
            self._ffmpeg_path,
            "-i", str(path),
            "-af", "loudnorm=I=-23:LRA=7:TP=-2:print_format=json",
            "-f", "null",
            os.devnull,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            result.errors.append("ffmpeg loudnorm timed out after 120s")
            return
        except OSError as exc:
            result.errors.append(f"ffmpeg error: {exc}")
            return

        # loudnorm prints JSON to stderr
        stderr = proc.stderr
        json_match = re.search(r"\{[^{}]+\}", stderr, re.DOTALL)
        if not json_match:
            result.warnings.append("loudnorm filter produced no JSON output")
            return

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError as exc:
            result.warnings.append(f"loudnorm JSON parse error: {exc}")
            return

        result.integrated_lufs = _float_or_none(data.get("input_i"))
        result.true_peak_dbtp = _float_or_none(data.get("input_tp"))
        result.loudness_range_lu = _float_or_none(data.get("input_lra"))

    # ── Step 4: pyloudnorm cross-check ───────────────────────────────────────

    def _measure_loudness_pyloudnorm(self, path: Path, result: AudioAnalysisResult) -> None:
        """
        Decode audio to PCM and measure with pyloudnorm as a cross-check.

        Only updates result if ffmpeg measurements are absent.  Requires:
        soundfile (reads PCM directly for WAV/FLAC/AIFF), or falls back to
        ffmpeg PCM decode for lossy formats.
        """
        try:
            import numpy as np
            import pyloudnorm as pyln
            import soundfile as sf
        except ImportError as exc:
            result.warnings.append(
                f"pyloudnorm/soundfile/numpy not available — skipping cross-check ({exc})"
            )
            return

        pcm_path: Path | None = None
        try:
            # soundfile can't read MP3/AAC; decode to temp WAV first
            if result.is_lossy or result.format in ("mp3", "aac", "m4a", "ogg", "opus"):
                pcm_path = self._decode_to_wav(path, result)
                if pcm_path is None:
                    return
                read_path = pcm_path
            else:
                read_path = path

            try:
                data, rate = sf.read(str(read_path), always_2d=True)
            except Exception as exc:
                result.warnings.append(f"soundfile read error: {exc}")
                return

            meter = pyln.Meter(rate)
            lufs = meter.integrated_loudness(data)

            # Only fill in if ffmpeg didn't provide a value
            if result.integrated_lufs is None and not (lufs != lufs):  # NaN check
                result.integrated_lufs = round(lufs, 2)

            # LRA measurement
            try:
                lra = meter.loudness_range(data)
                if result.loudness_range_lu is None and not (lra != lra):
                    result.loudness_range_lu = round(lra, 2)
            except Exception:
                pass  # LRA is optional

        except Exception as exc:
            result.warnings.append(f"pyloudnorm error: {exc}")
        finally:
            if pcm_path and pcm_path.exists():
                pcm_path.unlink(missing_ok=True)

    def _decode_to_wav(self, path: Path, result: AudioAnalysisResult) -> Path | None:
        """Decode any audio format to a temporary WAV file using ffmpeg."""
        if not self._ffmpeg_path:
            return None
        wav_path = path.parent / f"{path.stem}_pcm.wav"
        cmd = [
            self._ffmpeg_path,
            "-y", "-i", str(path),
            "-ac", "2",           # force stereo
            "-ar", "44100",       # resample for consistency
            "-f", "wav",
            str(wav_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            if proc.returncode != 0:
                result.warnings.append("ffmpeg WAV decode failed — pyloudnorm skipped")
                return None
            return wav_path
        except Exception as exc:
            result.warnings.append(f"ffmpeg WAV decode error: {exc}")
            return None

    # ── Step 5: AcoustID fingerprint ──────────────────────────────────────────

    def _fingerprint(self, path: Path, result: AudioAnalysisResult) -> None:
        """Generate an AcoustID fingerprint using pyacoustid + fpcalc."""
        if not self._fpcalc_path:
            result.warnings.append("fpcalc not found — AcoustID fingerprint skipped")
            return

        try:
            import acoustid  # type: ignore
        except ImportError:
            result.warnings.append("pyacoustid not installed — fingerprint skipped")
            return

        try:
            duration, fingerprint = acoustid.fingerprint_file(str(path))
            result.acoustid_fingerprint = fingerprint
            result.acoustid_duration = duration
        except Exception as exc:
            result.warnings.append(f"AcoustID fingerprint error: {exc}")

    # ── Step 7: silence detection ─────────────────────────────────────────────

    def _detect_silence(self, path: Path, result: AudioAnalysisResult) -> None:
        """
        Detect leading/trailing silence using ffmpeg silencedetect filter.
        Flags leading silence > 2s and trailing silence > 2s.
        """
        if not self._ffmpeg_path:
            return

        cmd = [
            self._ffmpeg_path,
            "-i", str(path),
            "-af", f"silencedetect=n={self.SILENCE_DB}dB:d={self.SILENCE_MIN_DURATION}",
            "-f", "null",
            os.devnull,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            return

        stderr = proc.stderr
        silence_starts = [
            float(m) for m in re.findall(r"silence_start: ([\d.]+)", stderr)
        ]
        silence_ends = [
            float(m) for m in re.findall(r"silence_end: ([\d.]+)", stderr)
        ]

        if silence_starts:
            # Leading silence: first silence_start is at 0 (or very close)
            if silence_starts[0] < 0.5:
                result.has_leading_silence = True

        if silence_ends and result.duration_seconds:
            # Trailing silence: last silence_end is near the end of the file
            last_end = silence_ends[-1]
            if result.duration_seconds - last_end < 0.5:
                result.has_trailing_silence = True


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find_binary(name: str) -> str | None:
    """Return the full path to a system binary, or None if not found."""
    import shutil
    return shutil.which(name)


def _url_suffix(url: str) -> str:
    """Extract file extension from URL path, e.g. '.flac'."""
    path = url.split("?")[0].rstrip("/")
    _, _, filename = path.rpartition("/")
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ""


def _float_or_none(value: Any) -> float | None:
    try:
        f = float(value)
        return None if (f != f) else f   # NaN → None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_kbps(value: Any) -> int | None:
    """Convert bit_rate string (bits/s) to kbps integer."""
    try:
        return int(int(value) / 1000)
    except (TypeError, ValueError):
        return None


def _guess_format(format_name: str, path: Path) -> str:
    """
    Normalise ffprobe format_name to a clean string.
    ffprobe may return comma-separated candidates like "wav,w64".
    """
    # Prefer file extension as ground truth
    ext = path.suffix.lower().lstrip(".")
    if ext in ("wav", "flac", "mp3", "aac", "ogg", "aiff", "aif", "m4a", "alac", "opus"):
        return ext

    # Fall back to first ffprobe format token
    first = format_name.split(",")[0].strip()
    mapping = {
        "wav": "wav", "w64": "wav",
        "flac": "flac",
        "mp3": "mp3", "mpeg": "mp3",
        "aac": "aac", "adts": "aac",
        "ogg": "ogg",
        "aiff": "aiff",
        "ipod": "m4a", "mov,mp4,m4a,3gp,3g2,mj2": "m4a",
        "opus": "opus",
    }
    return mapping.get(first, first)


def _extract_bit_depth(stream: dict) -> int | None:
    """
    Extract bit depth from an ffprobe audio stream dict.

    ffprobe stores it in different fields depending on the codec:
    - bits_per_sample (PCM codecs)
    - bits_per_raw_sample (FLAC, some others)
    - codec_name heuristic as fallback
    """
    # Direct fields
    for key in ("bits_per_sample", "bits_per_raw_sample"):
        v = stream.get(key)
        if v and int(v) > 0:
            return int(v)

    # Codec name heuristic
    codec = (stream.get("codec_name") or "").lower()
    depth_map = {
        "pcm_s16le": 16, "pcm_s16be": 16,
        "pcm_s24le": 24, "pcm_s24be": 24,
        "pcm_s32le": 32, "pcm_s32be": 32,
        "pcm_f32le": 32, "pcm_f32be": 32,
        "flac": 0,       # ffprobe usually gives bits_per_raw_sample for FLAC
        "alac": 0,       # same
        "mp3": 0,        # lossy, n/a
        "aac": 0,
        "vorbis": 0,
        "opus": 0,
    }
    depth = depth_map.get(codec)
    if depth is not None:
        return depth if depth > 0 else None
    return None
