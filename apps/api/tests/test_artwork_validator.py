"""
Tests for services/artwork/validator.py

All tests use in-memory Pillow images — no real HTTP or S3 calls.
The _download() method is monkeypatched to write a Pillow-generated
image to a temp file, so the rest of the validation pipeline runs
exactly as in production.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure apps/api is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image

from services.artwork.validator import (
    ArtworkValidator,
    ArtworkAnalysisResult,
    ArtworkFinding,
    MIN_DIMENSION_PX,
    MAX_FILE_SIZE_BYTES,
    ACCEPTED_FORMATS,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_image(
    width: int = 3000,
    height: int = 3000,
    mode: str = "RGB",
    format: str = "JPEG",
    dpi: tuple[int, int] | None = (72, 72),
) -> bytes:
    """Return raw image bytes of a Pillow-generated image."""
    img = Image.new(mode, (width, height), color=(120, 80, 200))
    buf = io.BytesIO()
    save_kwargs: dict = {"format": format}
    if dpi:
        save_kwargs["dpi"] = dpi
    img.save(buf, **save_kwargs)
    return buf.getvalue()


def _write_tmp(data: bytes, suffix: str = ".jpg") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, data)
    os.close(fd)
    return path


def _patch_download(tmp_path: str):
    """Context manager that patches _download() to return a pre-built temp file."""
    def fake_download(self, url: str) -> str:
        return tmp_path
    return patch.object(ArtworkValidator, "_download", fake_download)


def _validate_image(
    width: int = 3000,
    height: int = 3000,
    mode: str = "RGB",
    format: str = "JPEG",
    dpi: tuple[int, int] | None = (72, 72),
) -> ArtworkAnalysisResult:
    """Build a real image, write to disk, run validator, clean up."""
    suffix = ".jpg" if format == "JPEG" else ".png"
    data = _make_image(width=width, height=height, mode=mode, format=format, dpi=dpi)
    tmp = _write_tmp(data, suffix=suffix)
    try:
        validator = ArtworkValidator()
        with _patch_download(tmp):
            return validator.validate("fake://test")
    finally:
        # The validator deletes the file itself; only clean up if still present
        if os.path.exists(tmp):
            os.unlink(tmp)


def _finding_ids(result: ArtworkAnalysisResult) -> list[str]:
    return [f.rule_id for f in result.findings]


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkValidatorHappyPath(unittest.TestCase):

    def test_valid_jpeg_3000x3000_rgb(self):
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        self.assertTrue(result.succeeded)
        critical = [f for f in result.findings if f.severity == "critical"]
        self.assertEqual(critical, [], f"Unexpected critical findings: {critical}")

    def test_valid_png_4000x4000_rgb(self):
        result = _validate_image(4000, 4000, "RGB", "PNG")
        self.assertTrue(result.succeeded)
        critical = [f for f in result.findings if f.severity == "critical"]
        self.assertEqual(critical, [])

    def test_passes_property_true_for_clean_image(self):
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        self.assertTrue(result.passes)

    def test_format_set_correctly(self):
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        self.assertEqual(result.format, "jpeg")

    def test_dimensions_set_correctly(self):
        result = _validate_image(3500, 3500, "RGB", "JPEG")
        self.assertEqual(result.width, 3500)
        self.assertEqual(result.height, 3500)

    def test_color_mode_set_correctly(self):
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        self.assertEqual(result.color_mode, "RGB")


# ──────────────────────────────────────────────────────────────────────────────
# Format checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkFormatChecks(unittest.TestCase):

    def test_jpeg_accepted(self):
        result = _validate_image(3000, 3000, format="JPEG")
        self.assertNotIn("universal.artwork.format_not_accepted", _finding_ids(result))

    def test_png_accepted(self):
        result = _validate_image(3000, 3000, format="PNG")
        self.assertNotIn("universal.artwork.format_not_accepted", _finding_ids(result))

    def test_bmp_rejected(self):
        # BMP: write manually since Pillow BMP has no DPI in the same way
        img = Image.new("RGB", (3000, 3000), (100, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        tmp = _write_tmp(buf.getvalue(), suffix=".bmp")
        try:
            validator = ArtworkValidator()
            with _patch_download(tmp):
                result = validator.validate("fake://test")
            self.assertIn("universal.artwork.format_not_accepted", _finding_ids(result))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# Dimension checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkDimensionChecks(unittest.TestCase):

    def test_resolution_too_low_2000x2000(self):
        result = _validate_image(2000, 2000)
        self.assertIn("universal.artwork.resolution_too_low", _finding_ids(result))

    def test_resolution_too_low_is_critical(self):
        result = _validate_image(2000, 2000)
        finding = next(f for f in result.findings if f.rule_id == "universal.artwork.resolution_too_low")
        self.assertEqual(finding.severity, "critical")

    def test_resolution_3000x3000_no_critical(self):
        result = _validate_image(3000, 3000)
        self.assertNotIn("universal.artwork.resolution_too_low", _finding_ids(result))

    def test_resolution_below_recommended_3500x3500(self):
        result = _validate_image(3500, 3500)
        self.assertIn("universal.artwork.resolution_below_recommended", _finding_ids(result))

    def test_resolution_4000x4000_no_recommendation(self):
        result = _validate_image(4000, 4000)
        self.assertNotIn("universal.artwork.resolution_below_recommended", _finding_ids(result))


# ──────────────────────────────────────────────────────────────────────────────
# Aspect ratio checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkAspectRatioChecks(unittest.TestCase):

    def test_square_passes(self):
        result = _validate_image(3000, 3000)
        self.assertNotIn("universal.artwork.not_square", _finding_ids(result))

    def test_non_square_3000x2000_flagged(self):
        result = _validate_image(3000, 2000)
        self.assertIn("universal.artwork.not_square", _finding_ids(result))

    def test_non_square_is_critical(self):
        result = _validate_image(3000, 2000)
        finding = next(f for f in result.findings if f.rule_id == "universal.artwork.not_square")
        self.assertEqual(finding.severity, "critical")

    def test_non_square_1x2_flagged(self):
        # Very thin strip
        result = _validate_image(3000, 1500)
        self.assertIn("universal.artwork.not_square", _finding_ids(result))


# ──────────────────────────────────────────────────────────────────────────────
# Color mode checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkColorModeChecks(unittest.TestCase):

    def test_rgb_no_color_mode_finding(self):
        result = _validate_image(3000, 3000, mode="RGB")
        color_findings = [f for f in result.findings if "color" in f.rule_id or "cmyk" in f.rule_id]
        self.assertEqual(color_findings, [])

    def test_cmyk_flagged_critical(self):
        # CMYK JPEG
        img = Image.new("CMYK", (3000, 3000), (0, 50, 100, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        tmp = _write_tmp(buf.getvalue(), suffix=".jpg")
        try:
            validator = ArtworkValidator()
            with _patch_download(tmp):
                result = validator.validate("fake://test")
            self.assertIn("universal.artwork.cmyk_color_space", _finding_ids(result))
            finding = next(f for f in result.findings if f.rule_id == "universal.artwork.cmyk_color_space")
            self.assertEqual(finding.severity, "critical")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_palette_mode_flagged_critical(self):
        img = Image.new("P", (3000, 3000))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        tmp = _write_tmp(buf.getvalue(), suffix=".png")
        try:
            validator = ArtworkValidator()
            with _patch_download(tmp):
                result = validator.validate("fake://test")
            self.assertIn("universal.artwork.palette_color_mode", _finding_ids(result))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_rgba_flagged_warning(self):
        img = Image.new("RGBA", (3000, 3000), (100, 150, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        tmp = _write_tmp(buf.getvalue(), suffix=".png")
        try:
            validator = ArtworkValidator()
            with _patch_download(tmp):
                result = validator.validate("fake://test")
            self.assertIn("universal.artwork.has_transparency", _finding_ids(result))
            finding = next(f for f in result.findings if f.rule_id == "universal.artwork.has_transparency")
            self.assertEqual(finding.severity, "warning")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# File size checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkFileSizeChecks(unittest.TestCase):

    def test_file_size_too_large(self):
        """Simulate an oversized file by patching file_size_bytes after decode."""
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        # Manually set oversized and re-run only the size check
        result.file_size_bytes = MAX_FILE_SIZE_BYTES + 1
        validator = ArtworkValidator()
        validator._check_file_size(result)
        self.assertIn("universal.artwork.file_size_too_large", _finding_ids(result))

    def test_file_size_within_limit(self):
        result = _validate_image(3000, 3000, "RGB", "JPEG")
        # Normal JPEG should be well under 10 MB
        self.assertIsNotNone(result.file_size_bytes)
        self.assertLess(result.file_size_bytes, MAX_FILE_SIZE_BYTES)
        self.assertNotIn("universal.artwork.file_size_too_large", _finding_ids(result))


# ──────────────────────────────────────────────────────────────────────────────
# DPI checks
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkDPIChecks(unittest.TestCase):

    def test_dpi_72_no_finding(self):
        result = _validate_image(3000, 3000, dpi=(72, 72))
        self.assertNotIn("universal.artwork.dpi_too_low", _finding_ids(result))
        self.assertNotIn("universal.artwork.dpi_not_set", _finding_ids(result))

    def test_dpi_below_72_warning(self):
        result = _validate_image(3000, 3000, dpi=(50, 50))
        self.assertIn("universal.artwork.dpi_too_low", _finding_ids(result))

    def test_dpi_between_72_and_300_info(self):
        result = _validate_image(3000, 3000, dpi=(96, 96))
        self.assertIn("universal.artwork.dpi_below_recommended", _finding_ids(result))

    def test_dpi_300_no_advisory(self):
        result = _validate_image(3000, 3000, dpi=(300, 300))
        self.assertNotIn("universal.artwork.dpi_too_low", _finding_ids(result))
        self.assertNotIn("universal.artwork.dpi_below_recommended", _finding_ids(result))

    def test_no_dpi_metadata_info_finding(self):
        result = _validate_image(3000, 3000, dpi=None)
        self.assertIn("universal.artwork.dpi_not_set", _finding_ids(result))


# ──────────────────────────────────────────────────────────────────────────────
# Text-heaviness heuristic
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkTextHeaviness(unittest.TestCase):

    def test_solid_color_not_text_heavy(self):
        """A solid color image is not text-heavy (no contrast)."""
        img = Image.new("RGB", (200, 200), (150, 80, 200))
        validator = ArtworkValidator()
        self.assertFalse(validator._check_text_heaviness(img))

    def test_high_contrast_bw_is_text_heavy(self):
        """
        Black text on white background: high achromatic fraction + high contrast.
        Simulate by filling with alternating black/white rows.
        """
        import numpy as np
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        arr[::2, :] = 255   # white rows
        # arr[1::2] stays black
        from PIL import Image as PILImage
        img = PILImage.fromarray(arr, mode="RGB")
        validator = ArtworkValidator()
        self.assertTrue(validator._check_text_heaviness(img))

    def test_colorful_photo_not_text_heavy(self):
        """A colorful gradient should not trigger the text-heavy heuristic."""
        import numpy as np
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        # Rainbow-ish gradient: high saturation throughout
        for x in range(200):
            arr[:, x, 0] = int(x * 255 / 200)        # R
            arr[:, x, 1] = int((200 - x) * 255 / 200) # G
            arr[:, x, 2] = 128                          # B
        from PIL import Image as PILImage
        img = PILImage.fromarray(arr, mode="RGB")
        validator = ArtworkValidator()
        self.assertFalse(validator._check_text_heaviness(img))


# ──────────────────────────────────────────────────────────────────────────────
# Download failure handling
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkDownloadErrors(unittest.TestCase):

    def test_download_failure_returns_failed_result(self):
        from services.artwork.validator import _DownloadError

        def failing_download(self, url):
            raise _DownloadError("Connection refused")

        with patch.object(ArtworkValidator, "_download", failing_download):
            validator = ArtworkValidator()
            result = validator.validate("http://bad.url/art.jpg")

        self.assertFalse(result.succeeded)
        self.assertTrue(any("Download failed" in e for e in result.errors))

    def test_corrupt_image_returns_failed_result(self):
        """Pillow raises UnidentifiedImageError on non-image data."""
        tmp = _write_tmp(b"this is not an image", suffix=".jpg")
        try:
            validator = ArtworkValidator()
            with _patch_download(tmp):
                result = validator.validate("fake://test")
            self.assertFalse(result.succeeded)
            self.assertTrue(any("could not identify" in e.lower() for e in result.errors))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# ArtworkAnalysisResult.to_dict()
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkAnalysisResultToDict(unittest.TestCase):

    def test_to_dict_keys(self):
        result = _validate_image(3000, 3000)
        d = result.to_dict()
        for key in ("artwork_url", "width", "height", "format", "color_mode",
                    "file_size_bytes", "dpi_x", "succeeded", "passes", "findings", "errors"):
            self.assertIn(key, d)

    def test_to_dict_findings_structure(self):
        result = _validate_image(2000, 2000)  # should have resolution_too_low
        d = result.to_dict()
        self.assertTrue(len(d["findings"]) > 0)
        f = d["findings"][0]
        for key in ("rule_id", "severity", "message", "fix_hint", "actual_value"):
            self.assertIn(key, f)


if __name__ == "__main__":
    unittest.main()
