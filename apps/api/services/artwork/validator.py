"""
Artwork validation service.

Validates cover art images against DSP requirements using Pillow.

Pipeline (per artwork file)
───────────────────────────
1. Download from S3 or HTTP to a /tmp UUID file
2. Decode with Pillow — raises on corrupt/unsupported images
3. Check dimensions    (min 3000×3000 px for all DSPs)
4. Check aspect ratio  (must be 1:1 square)
5. Check color mode    (RGB required; CMYK, P, L, RGBA all flagged)
6. Check format        (JPEG or PNG; TIFF/BMP etc. not accepted)
7. Check file size     (max 10 MB — universal DSP ceiling)
8. Check DPI           (advisory: 72+ recommended; 300+ ideal for print)
9. Text-heaviness heuristic  (high-contrast, low-saturation regions = likely text overlay)
10. Cleanup temp file (always)

Dependencies
────────────
Python: Pillow, httpx, boto3, numpy
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

MIN_DIMENSION_PX = 3000           # universal: Spotify, Apple, YouTube, Amazon, TikTok
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB

ACCEPTED_FORMATS = {"jpeg", "png"}  # lowercase Pillow format names
ACCEPTED_MODES   = {"RGB"}

# Text-heaviness heuristic: if the proportion of pixels in
# "high-contrast low-saturation" zones exceeds this threshold,
# we warn that the artwork may be text-heavy.
TEXT_ZONE_FRACTION_THRESHOLD = 0.25

# DPI thresholds (from EXIF / image metadata)
DPI_MINIMUM  = 72
DPI_ADVISORY = 300

# Download
_DOWNLOAD_TIMEOUT_S = 30
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # refuse >20 MB to protect workers


# ──────────────────────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ArtworkFinding:
    """
    A single validation finding from artwork analysis.

    rule_id follows the convention ``<dsp_or_universal>.artwork.<slug>``.
    severity: "critical" | "warning" | "info"
    """
    rule_id: str
    severity: str        # "critical" | "warning" | "info"
    message: str
    fix_hint: str | None = None
    actual_value: str | None = None


@dataclass
class ArtworkAnalysisResult:
    """
    Full analysis result for a single artwork file.

    Numeric fields are None when not determined (e.g. corrupt image).
    ``findings`` contains all rule violations; an empty list = fully passing.
    ``succeeded`` is False only when the image could not be decoded at all.
    """
    artwork_url: str

    # Decoded image properties
    width: int | None = None
    height: int | None = None
    format: str | None = None          # "jpeg" | "png" | "tiff" | …
    color_mode: str | None = None      # "RGB" | "CMYK" | "P" | …
    file_size_bytes: int | None = None
    dpi_x: float | None = None
    dpi_y: float | None = None
    has_transparency: bool = False
    is_text_heavy: bool = False        # heuristic: artwork appears to be mostly text
    analysis_duration_seconds: float | None = None

    # Outcome
    succeeded: bool = True
    findings: list[ArtworkFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        """True if there are no critical findings."""
        return self.succeeded and not any(
            f.severity == "critical" for f in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artwork_url": self.artwork_url,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "color_mode": self.color_mode,
            "file_size_bytes": self.file_size_bytes,
            "dpi_x": self.dpi_x,
            "dpi_y": self.dpi_y,
            "has_transparency": self.has_transparency,
            "is_text_heavy": self.is_text_heavy,
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "succeeded": self.succeeded,
            "passes": self.passes,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "message": f.message,
                    "fix_hint": f.fix_hint,
                    "actual_value": f.actual_value,
                }
                for f in self.findings
            ],
            "errors": self.errors,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Validator
# ──────────────────────────────────────────────────────────────────────────────

class ArtworkValidator:
    """
    Validates cover-art images against DSP delivery requirements.

    Usage::

        validator = ArtworkValidator()
        result = validator.validate("https://…/cover.jpg")
        if not result.passes:
            for finding in result.findings:
                print(finding.rule_id, finding.severity, finding.message)

    Thread-safety: stateless — safe to share across threads.
    """

    def validate(self, artwork_url: str) -> ArtworkAnalysisResult:
        """
        Download, decode, and validate a cover-art image.

        Never raises — all exceptions are caught and returned as
        ``ArtworkAnalysisResult(succeeded=False, errors=[…])``.
        """
        result = ArtworkAnalysisResult(artwork_url=artwork_url)
        tmp_path: str | None = None
        t0 = time.perf_counter()

        try:
            tmp_path = self._download(artwork_url)
            result.file_size_bytes = os.path.getsize(tmp_path)
            self._decode_and_check(tmp_path, result)
        except _DownloadError as exc:
            result.succeeded = False
            result.errors.append(f"Download failed: {exc}")
        except UnidentifiedImageError:
            result.succeeded = False
            result.errors.append("Pillow could not identify image format — file may be corrupt.")
        except Exception as exc:  # noqa: BLE001
            result.succeeded = False
            result.errors.append(f"Unexpected error during artwork analysis: {exc}")
            logger.exception("ArtworkValidator.validate() failed for %s", artwork_url)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            result.analysis_duration_seconds = round(time.perf_counter() - t0, 3)

        return result

    # ── download ──────────────────────────────────────────────────────────────

    def _download(self, url: str) -> str:
        """
        Download artwork to a temp file.  Returns the temp file path.

        Supports:
          - data:image/...;base64,…  (inline data URI)
          - s3://bucket/key          (boto3 — uses IAM/env credentials)
          - https:// / http://
        """
        parsed = urlparse(url)

        if parsed.scheme == "data":
            # data:image/jpeg;base64,<payload>
            import base64 as _b64
            header, _, payload = url.partition(",")
            raw = _b64.b64decode(payload) if ";base64" in header else payload.encode()
            # Sniff extension from MIME type in header
            mime = header.split(":")[1].split(";")[0] if ":" in header else ""
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".bin")
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=f"ropqa-art-{uuid.uuid4().hex[:8]}-", suffix=ext
            )
            os.close(tmp_fd)
            with open(tmp_path, "wb") as f:
                f.write(raw)
            return tmp_path

        # Generate a stable extension from the URL path for Pillow format hints
        suffix = Path(parsed.path).suffix or ".bin"
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f"ropqa-art-{uuid.uuid4().hex[:8]}-",
            suffix=suffix,
        )
        os.close(tmp_fd)

        try:
            if parsed.scheme == "s3":
                self._download_s3(parsed.netloc, parsed.path.lstrip("/"), tmp_path)
            else:
                self._download_http(url, tmp_path)
        except Exception as exc:
            # Clean up on download failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise _DownloadError(str(exc)) from exc

        return tmp_path

    def _download_s3(self, bucket: str, key: str, dest: str) -> None:
        import boto3  # lazy import — not always available in test environments
        from config import settings

        kwargs: dict = {"region_name": settings.aws_region}
        if getattr(settings, "aws_access_key_id", None):
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if getattr(settings, "s3_endpoint_url", None):
            kwargs["endpoint_url"] = settings.s3_endpoint_url

        s3 = boto3.client("s3", **kwargs)
        s3.download_file(bucket, key, dest)

    def _download_http(self, url: str, dest: str) -> None:
        with httpx.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True) as resp:
            resp.raise_for_status()
            size = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > _MAX_DOWNLOAD_BYTES:
                        raise _DownloadError(
                            f"Artwork file exceeds {_MAX_DOWNLOAD_BYTES // 1024 // 1024} MB limit"
                        )
                    fh.write(chunk)

    # ── image analysis ────────────────────────────────────────────────────────

    def _decode_and_check(self, path: str, result: ArtworkAnalysisResult) -> None:
        """Open image with Pillow and run all checks, populating result in-place."""
        with Image.open(path) as img:
            # ── populate basic properties ──────────────────────────────────
            result.width, result.height = img.size
            result.format = (img.format or "").lower() or None
            result.color_mode = img.mode
            result.has_transparency = img.mode in ("RGBA", "LA", "PA") or (
                img.mode == "P" and img.info.get("transparency") is not None
            )

            # DPI from EXIF / image metadata
            dpi = img.info.get("dpi")
            if dpi and isinstance(dpi, (tuple, list)) and len(dpi) == 2:
                result.dpi_x = float(dpi[0])
                result.dpi_y = float(dpi[1])

            # ── run all checks ─────────────────────────────────────────────
            self._check_format(result)
            self._check_file_size(result)
            self._check_dimensions(result)
            self._check_aspect_ratio(result)
            self._check_color_mode(result)
            self._check_dpi(result)

            # Text-heaviness requires pixel access — only run if image decoded OK
            try:
                result.is_text_heavy = self._check_text_heaviness(img)
                if result.is_text_heavy:
                    result.findings.append(ArtworkFinding(
                        rule_id="universal.artwork.text_heavy",
                        severity="warning",
                        message=(
                            "Artwork appears to contain significant text or graphic overlays. "
                            "Most DSPs prohibit text (other than the artist/title already in metadata) "
                            "on cover art."
                        ),
                        fix_hint=(
                            "Use a clean image without embedded text. "
                            "Artist name and title are already displayed by the DSP's UI."
                        ),
                    ))
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Text-heaviness check skipped: {exc}")

    # ── individual checks ──────────────────────────────────────────────────────

    def _check_format(self, result: ArtworkAnalysisResult) -> None:
        fmt = result.format
        if not fmt:
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.format_undetected",
                severity="critical",
                message="Image format could not be determined.",
                fix_hint="Provide a JPEG (.jpg) or PNG (.png) file.",
            ))
            return

        if fmt not in ACCEPTED_FORMATS:
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.format_not_accepted",
                severity="critical",
                message=(
                    f"Image format '{fmt.upper()}' is not accepted by any major DSP. "
                    f"Accepted formats: JPEG, PNG."
                ),
                fix_hint="Convert to JPEG (preferred for file size) or PNG.",
                actual_value=fmt.upper(),
            ))

    def _check_file_size(self, result: ArtworkAnalysisResult) -> None:
        size = result.file_size_bytes
        if size is None:
            return
        if size > MAX_FILE_SIZE_BYTES:
            mb = size / 1024 / 1024
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.file_size_too_large",
                severity="critical",
                message=(
                    f"Artwork file size {mb:.1f} MB exceeds the 10 MB limit "
                    f"enforced by Spotify and Apple Music."
                ),
                fix_hint=(
                    "Reduce file size by converting to JPEG with quality 85–95, "
                    "or by exporting at exactly 3000×3000 px."
                ),
                actual_value=f"{mb:.1f} MB",
            ))

    def _check_dimensions(self, result: ArtworkAnalysisResult) -> None:
        w, h = result.width, result.height
        if w is None or h is None:
            return

        if w < MIN_DIMENSION_PX or h < MIN_DIMENSION_PX:
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.resolution_too_low",
                severity="critical",
                message=(
                    f"Artwork dimensions {w}×{h} px are below the universal minimum "
                    f"of {MIN_DIMENSION_PX}×{MIN_DIMENSION_PX} px required by all major DSPs."
                ),
                fix_hint=(
                    f"Re-export artwork at {MIN_DIMENSION_PX}×{MIN_DIMENSION_PX} px or larger. "
                    f"3000×3000 px at 72 DPI is the baseline; 3000×3000 at 300 DPI is ideal."
                ),
                actual_value=f"{w}×{h} px",
            ))
        elif w < 4000 or h < 4000:
            # Apple Music recommends 4000×4000 for editorial
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.resolution_below_recommended",
                severity="info",
                message=(
                    f"Artwork dimensions {w}×{h} px meet the minimum but are below the "
                    f"4000×4000 px size recommended by Apple Music for editorial placement."
                ),
                fix_hint="Consider providing artwork at 4000×4000 px or larger for best editorial results.",
                actual_value=f"{w}×{h} px",
            ))

    def _check_aspect_ratio(self, result: ArtworkAnalysisResult) -> None:
        w, h = result.width, result.height
        if w is None or h is None or h == 0:
            return

        ratio = w / h
        if abs(ratio - 1.0) > 0.01:   # allow ±1% tolerance for rounding
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.not_square",
                severity="critical",
                message=(
                    f"Artwork must be square (1:1 aspect ratio). "
                    f"Current dimensions are {w}×{h} px ({ratio:.3f}:1)."
                ),
                fix_hint=(
                    "Crop or pad the image to a perfect square before delivering. "
                    "All DSPs require square cover art."
                ),
                actual_value=f"{w}×{h} px",
            ))

    def _check_color_mode(self, result: ArtworkAnalysisResult) -> None:
        mode = result.color_mode
        if mode is None:
            return

        if mode == "CMYK":
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.cmyk_color_space",
                severity="critical",
                message=(
                    "Artwork is in CMYK color space. DSPs require RGB. "
                    "CMYK images are rejected by Spotify and Apple Music."
                ),
                fix_hint="Convert to RGB color space in Photoshop (Image → Mode → RGB Color).",
                actual_value="CMYK",
            ))
        elif mode == "P":
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.palette_color_mode",
                severity="critical",
                message=(
                    "Artwork is in indexed/palette (P) mode, which limits color depth to 256 colors. "
                    "DSPs require full RGB."
                ),
                fix_hint="Convert to RGB mode. In Pillow: image.convert('RGB').",
                actual_value="P (indexed)",
            ))
        elif mode in ("L", "LA"):
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.grayscale_color_mode",
                severity="warning",
                message=(
                    f"Artwork is in grayscale ({mode}) mode. "
                    "While technically valid, most DSPs expect and display RGB artwork. "
                    "Apple Music will convert but may alter appearance."
                ),
                fix_hint="Convert to RGB mode even for black-and-white artwork.",
                actual_value=mode,
            ))
        elif mode == "RGBA":
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.has_transparency",
                severity="warning",
                message=(
                    "Artwork has an alpha channel (RGBA). Most DSPs strip transparency "
                    "and composite against a white or black background, which may alter appearance."
                ),
                fix_hint=(
                    "Flatten transparency before delivery: composite onto a white background "
                    "and export as RGB JPEG."
                ),
                actual_value="RGBA",
            ))

    def _check_dpi(self, result: ArtworkAnalysisResult) -> None:
        dpi_x = result.dpi_x
        if dpi_x is None:
            # Many web images omit DPI metadata; not a hard failure
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.dpi_not_set",
                severity="info",
                message=(
                    "Artwork does not have DPI metadata embedded. "
                    "Some DSP ingest pipelines expect 72+ DPI in image metadata."
                ),
                fix_hint=(
                    "Re-export with DPI metadata set to 72 (web) or 300 (print quality). "
                    "This does not affect pixel dimensions — only metadata."
                ),
            ))
            return

        if dpi_x < DPI_MINIMUM:
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.dpi_too_low",
                severity="warning",
                message=(
                    f"Artwork DPI ({dpi_x:.0f}) is below the recommended minimum of {DPI_MINIMUM} DPI. "
                    "Some DSP ingest pipelines will reject images below 72 DPI."
                ),
                fix_hint=f"Re-export with DPI set to at least {DPI_MINIMUM}.",
                actual_value=f"{dpi_x:.0f} DPI",
            ))
        elif dpi_x < DPI_ADVISORY:
            result.findings.append(ArtworkFinding(
                rule_id="universal.artwork.dpi_below_recommended",
                severity="info",
                message=(
                    f"Artwork DPI ({dpi_x:.0f}) is below the recommended {DPI_ADVISORY} DPI. "
                    "For best print and high-DPI display quality, 300 DPI is ideal."
                ),
                fix_hint=f"Re-export with DPI set to {DPI_ADVISORY} for optimal quality.",
                actual_value=f"{dpi_x:.0f} DPI",
            ))

    # ── text-heaviness heuristic ──────────────────────────────────────────────

    def _check_text_heaviness(self, img: Image.Image) -> bool:
        """
        Heuristic: detect artwork that is mostly text/graphic rather than photography.

        Approach: convert to RGB, compute per-pixel saturation.
        Text on solid backgrounds tends to have:
          - Low saturation (white/black/grey text)
          - High local contrast

        We use the fraction of near-achromatic pixels as a proxy.
        This is deliberately conservative — it flags heavily watermarked
        or text-overlay artwork, not clean designs with a logo.

        Returns True if artwork is likely text-heavy.
        """
        # Downsample for speed — we don't need full resolution for this heuristic
        small = img.convert("RGB").resize((200, 200), Image.LANCZOS)
        arr = np.array(small, dtype=np.float32)   # shape (200, 200, 3)

        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        cmax = np.maximum(np.maximum(r, g), b)
        cmin = np.minimum(np.minimum(r, g), b)

        # Saturation in HSV: (max - min) / max, with 0 when max == 0
        sat = np.where(cmax > 0, (cmax - cmin) / cmax, 0.0)

        # Value (brightness)
        val = cmax / 255.0

        # "Near-achromatic": low saturation AND either very dark or very light
        # These pixels are candidates for text / solid backgrounds
        near_achromatic = (sat < 0.15) & ((val < 0.1) | (val > 0.85))
        achromatic_fraction = float(np.mean(near_achromatic))

        # If most of the image is near-achromatic we also need contrast,
        # otherwise it could just be a white background with a colorful logo.
        # Compute std-dev of the grayscale channel across the full image.
        gray = 0.299 * r + 0.587 * g + 0.114 * b
        contrast = float(np.std(gray)) / 255.0

        return achromatic_fraction > TEXT_ZONE_FRACTION_THRESHOLD and contrast > 0.15


# ──────────────────────────────────────────────────────────────────────────────
# Private exceptions
# ──────────────────────────────────────────────────────────────────────────────

class _DownloadError(Exception):
    """Raised when the artwork file cannot be downloaded."""
