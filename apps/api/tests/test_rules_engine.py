"""
Tests for the DSP metadata rules engine.

Coverage:
  DSPRulesEngine loading
    - Loads rules from YAML files
    - Rule count is non-zero
    - Universal rules have dsp=None
    - DSP-specific rules have correct dsp slug

  Safe expression evaluator
    - Disallows eval-equivalent constructs (__import__, etc.)
    - Disallows attribute access on non-metadata objects
    - Disallows unwhitelisted function calls
    - Evaluates comparisons correctly
    - Evaluates boolean ops correctly
    - Evaluates whitelisted functions correctly
    - Raises EvalError on unknown variable
    - Raises EvalError on method call

  ISRC rules
    - Missing ISRC (empty isrc_list)        → universal.metadata.isrc_present: fail
    - Invalid ISRC format                   → universal.metadata.isrc_format: fail
    - Valid ISRC format                     → universal.metadata.isrc_format: pass
    - Duplicate ISRCs                       → universal.metadata.isrc_unique: fail
    - No duplicates                         → universal.metadata.isrc_unique: pass
    - All three ISRC checks pass together   → combined pass

  Artwork rules
    - Missing artwork (width=0)             → universal.artwork.minimum_resolution: fail
    - Wrong resolution (640x640)            → universal.artwork.minimum_resolution: fail
    - Correct resolution (3000x3000)        → universal.artwork.minimum_resolution: pass
    - Non-square artwork                    → universal.artwork.must_be_square: fail
    - Wrong color mode CMYK (apple rule)    → apple.artwork.rgb_color_space_required: fail
    - Correct color mode RGB               → apple.artwork.rgb_color_space_required: pass
    - Wrong format (bmp)                   → universal.artwork.format_must_be_jpeg_or_png: fail
    - Correct format (jpeg)                → universal.artwork.format_must_be_jpeg_or_png: pass

  Publisher rules
    - Missing publisher                     → spotify.metadata.contributor_publisher_required: fail
    - Publisher present                     → spotify.metadata.contributor_publisher_required: pass

  Genre rules
    - Missing genre                         → universal.metadata.genre_required: fail (warning)
    - Genre present                         → universal.metadata.genre_required: pass

  Explicit content flag rules
    - Missing parental_warning              → spotify.metadata.explicit_content_flag: fail
    - parental_warning = "Explicit"         → pass
    - parental_warning = "NotExplicit"      → pass
    - parental_warning = "Clean"            → pass
    - parental_warning = "Yes" (invalid)    → spotify.metadata.explicit_flag_valid_value: fail
    - parental_warning = "1" (invalid)      → fail
    - apple advisory rating: same checks    → apple.metadata.advisory_rating_valid_value

  evaluate() targeting
    - dsps=["spotify"] runs spotify + universal, NOT apple/youtube/amazon/tiktok
    - dsps=["apple"] runs apple + universal, NOT spotify rules
    - dsps=[] runs universal only
    - Default dsps runs all 5 DSPs + universal

  RuleResult structure
    - status in {"pass", "fail", "skip"}
    - severity mirrors rule definition
    - fix_hint populated on fail, None on pass
    - checked_value reflects the actual field value
"""

from __future__ import annotations

import pytest
from pathlib import Path

from services.metadata.rules_engine import (
    DSPRulesEngine,
    EvalError,
    ReleaseMetadata,
    RuleDefinition,
    RuleResult,
    _safe_eval,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

RULES_DIR = Path(__file__).parent.parent / "rules" / "dsp"


@pytest.fixture(scope="module")
def engine() -> DSPRulesEngine:
    return DSPRulesEngine(rules_dir=RULES_DIR)


def _good_meta(**overrides) -> ReleaseMetadata:
    """Fully valid metadata; override any field to test a specific failure."""
    defaults = dict(
        title="Test Album",
        artist="Test Artist",
        upc="123456789012",
        label="Test Label LLC",
        release_date="2024-06-01",
        release_type="Album",
        genre="Pop",
        language="en",
        c_line="2024 Test Label LLC",
        p_line="2024 Test Label LLC",
        p_line_year="2024",
        publisher="Test Publishing Co.",
        parental_warning="NotExplicit",
        artwork_width=3000,
        artwork_height=3000,
        artwork_format="jpeg",
        artwork_color_mode="RGB",
        sample_rate=44100,
        bit_depth=16,
        isrc_list=["GB-ABC-24-00001"],
        territory="Worldwide",
    )
    defaults.update(overrides)
    return ReleaseMetadata(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# Engine loading
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineLoading:
    def test_loads_rules(self, engine: DSPRulesEngine):
        assert engine.rule_count > 0

    def test_universal_rules_have_no_dsp(self, engine: DSPRulesEngine):
        universals = [r for r in engine.list_rules(active_only=False) if r.dsp is None]
        assert len(universals) > 0

    def test_spotify_rules_have_dsp_spotify(self, engine: DSPRulesEngine):
        spotify_rules = [r for r in engine.list_rules(active_only=False) if r.dsp == "spotify"]
        assert len(spotify_rules) > 0

    def test_apple_rules_have_dsp_apple(self, engine: DSPRulesEngine):
        apple_rules = [r for r in engine.list_rules(active_only=False) if r.dsp == "apple"]
        assert len(apple_rules) > 0

    def test_youtube_rules_loaded(self, engine: DSPRulesEngine):
        youtube_rules = [r for r in engine.list_rules(active_only=False) if r.dsp == "youtube"]
        assert len(youtube_rules) > 0

    def test_amazon_rules_loaded(self, engine: DSPRulesEngine):
        amazon_rules = [r for r in engine.list_rules(active_only=False) if r.dsp == "amazon"]
        assert len(amazon_rules) > 0

    def test_tiktok_rules_loaded(self, engine: DSPRulesEngine):
        tiktok_rules = [r for r in engine.list_rules(active_only=False) if r.dsp == "tiktok"]
        assert len(tiktok_rules) > 0

    def test_get_specific_rule(self, engine: DSPRulesEngine):
        rule = engine.get_rule("universal.metadata.isrc_present")
        assert rule is not None
        assert rule.severity == "critical"
        assert rule.check is not None

    def test_rules_have_required_fields(self, engine: DSPRulesEngine):
        for rule in engine.list_rules():
            assert rule.id
            assert rule.layer
            assert rule.severity in {"critical", "warning", "info", "error"}
            assert rule.title


# ──────────────────────────────────────────────────────────────────────────────
# Safe expression evaluator unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSafeEval:
    def _meta(self, **kw) -> ReleaseMetadata:
        return ReleaseMetadata(**kw)

    # ── Should evaluate correctly ─────────────────────────────────────────────
    def test_simple_string_comparison_true(self):
        m = self._meta(title="Hello")
        assert _safe_eval("metadata.title == 'Hello'", m) is True

    def test_simple_string_comparison_false(self):
        m = self._meta(title="Hello")
        assert _safe_eval("metadata.title == 'World'", m) is False

    def test_numeric_gte_true(self):
        m = self._meta(artwork_width=3000)
        assert _safe_eval("metadata.artwork_width >= 3000", m) is True

    def test_numeric_gte_false(self):
        m = self._meta(artwork_width=640)
        assert _safe_eval("metadata.artwork_width >= 3000", m) is False

    def test_boolean_and(self):
        m = self._meta(artwork_width=3000, artwork_height=3000)
        assert _safe_eval("metadata.artwork_width >= 3000 and metadata.artwork_height >= 3000", m)

    def test_boolean_or_short_circuits(self):
        m = self._meta(artwork_width=0, artwork_height=0)
        # 0 == 0 is True, so short-circuits
        assert _safe_eval("metadata.artwork_width == 0 or metadata.artwork_width >= 3000", m)

    def test_not_operator(self):
        m = self._meta(title="Hello")
        assert _safe_eval("not metadata.title == 'World'", m) is True

    def test_in_list_literal_true(self):
        m = self._meta(parental_warning="Explicit")
        assert _safe_eval("metadata.parental_warning in ['Explicit', 'NotExplicit', 'Clean']", m)

    def test_in_list_literal_false(self):
        m = self._meta(parental_warning="Yes")
        assert not _safe_eval("metadata.parental_warning in ['Explicit', 'NotExplicit', 'Clean']", m)

    def test_not_in_operator(self):
        m = self._meta(parental_warning="Bad")
        assert _safe_eval("metadata.parental_warning not in ['Explicit', 'NotExplicit', 'Clean']", m)

    def test_has_value_truthy(self):
        m = self._meta(title="My Album")
        assert _safe_eval("has_value(metadata.title)", m)

    def test_has_value_empty_string(self):
        m = self._meta(title="")
        assert not _safe_eval("has_value(metadata.title)", m)

    def test_has_value_whitespace_only(self):
        m = self._meta(title="   ")
        assert not _safe_eval("has_value(metadata.title)", m)

    def test_has_value_empty_list(self):
        m = self._meta(isrc_list=[])
        assert not _safe_eval("has_value(metadata.isrc_list)", m)

    def test_regex_match_valid_isrc(self):
        m = self._meta()
        expr = r"regex_match(metadata.upc, '^\d{12,13}$')"
        m.upc = "123456789012"
        assert _safe_eval(expr, m)

    def test_regex_match_invalid(self):
        m = self._meta(upc="NOTAUPC")
        assert not _safe_eval(r"regex_match(metadata.upc, '^\d{12,13}$')", m)

    def test_all_items_match_valid_isrcs(self):
        m = self._meta(isrc_list=["GB-ABC-24-00001", "US-XYZ-23-99999"])
        pattern = r"^[A-Z]{2}-?[A-Z0-9]{3}-?\d{2}-?\d{5}$"
        assert _safe_eval(f"all_items_match(metadata.isrc_list, '{pattern}')", m)

    def test_all_items_match_invalid_isrc(self):
        m = self._meta(isrc_list=["GB-ABC-24-00001", "BADISRC"])
        pattern = r"^[A-Z]{2}-?[A-Z0-9]{3}-?\d{2}-?\d{5}$"
        assert not _safe_eval(f"all_items_match(metadata.isrc_list, '{pattern}')", m)

    def test_no_duplicates_unique(self):
        m = self._meta(isrc_list=["GB-ABC-24-00001", "GB-ABC-24-00002"])
        assert _safe_eval("no_duplicates(metadata.isrc_list)", m)

    def test_no_duplicates_has_duplicate(self):
        m = self._meta(isrc_list=["GB-ABC-24-00001", "GB-ABC-24-00001"])
        assert not _safe_eval("no_duplicates(metadata.isrc_list)", m)

    def test_len_function(self):
        m = self._meta(isrc_list=["A", "B", "C"])
        assert _safe_eval("len(metadata.isrc_list) > 0", m)

    def test_contains_function(self):
        m = self._meta(title="My Song (Radio Edit)")
        assert _safe_eval("contains(metadata.title, '(Radio Edit)')", m)
        assert not _safe_eval("contains(metadata.title, '(feat.')", m)

    def test_abs_function(self):
        m = self._meta(loudness_lufs=-14.0)
        assert _safe_eval("abs(metadata.loudness_lufs) < 16.0", m)

    # ── Should raise EvalError on disallowed constructs ───────────────────────
    def test_disallows_unknown_variable(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError, match="Unknown variable"):
            _safe_eval("evil_var == 1", m)

    def test_disallows_attribute_chain(self):
        m = ReleaseMetadata(title="x")
        with pytest.raises(EvalError):
            _safe_eval("metadata.title.upper()", m)

    def test_disallows_unknown_function(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError, match="not in the allowed function list"):
            _safe_eval("open('/etc/passwd')", m)

    def test_disallows_import(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError):
            _safe_eval("__import__('os')", m)

    def test_disallows_lambda(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError):
            _safe_eval("(lambda: True)()", m)

    def test_disallows_subscript_on_metadata(self):
        """Direct subscript like metadata['title'] is disallowed; use attribute access."""
        m = ReleaseMetadata(title="x")
        with pytest.raises(EvalError):
            _safe_eval("metadata['title']", m)

    def test_disallows_nonexistent_attribute(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError, match="has no field"):
            _safe_eval("metadata.nonexistent_field == 1", m)

    def test_syntax_error_raises_eval_error(self):
        m = ReleaseMetadata()
        with pytest.raises(EvalError, match="Syntax error"):
            _safe_eval("===bad syntax===", m)


# ──────────────────────────────────────────────────────────────────────────────
# ISRC rule tests
# ──────────────────────────────────────────────────────────────────────────────

class TestISRCRules:
    def test_missing_isrc_fails_present_rule(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=[])
        results = engine.evaluate(meta, dsps=["spotify"])
        present = _find(results, "universal.metadata.isrc_present")
        assert present is not None
        assert present.status == "fail"
        assert present.severity == "critical"

    def test_invalid_isrc_format_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["BADISRC"])
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.metadata.isrc_format")
        assert fmt is not None
        assert fmt.status == "fail"

    def test_valid_isrc_format_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["GB-ABC-24-00001"])
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.metadata.isrc_format")
        assert fmt is not None
        assert fmt.status == "pass"

    def test_valid_isrc_no_dashes_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["GBABC2400001"])
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.metadata.isrc_format")
        assert fmt is not None
        assert fmt.status == "pass"

    def test_duplicate_isrc_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["GB-ABC-24-00001", "GB-ABC-24-00001"])
        results = engine.evaluate(meta, dsps=["spotify"])
        uniq = _find(results, "universal.metadata.isrc_unique")
        assert uniq is not None
        assert uniq.status == "fail"

    def test_unique_isrcs_pass(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["GB-ABC-24-00001", "GB-ABC-24-00002"])
        results = engine.evaluate(meta, dsps=["spotify"])
        uniq = _find(results, "universal.metadata.isrc_unique")
        assert uniq is not None
        assert uniq.status == "pass"

    def test_all_isrc_rules_pass_for_good_data(self, engine: DSPRulesEngine):
        meta = _good_meta(isrc_list=["GB-ABC-24-00001", "GB-ABC-24-00002"])
        results = engine.evaluate(meta, dsps=["spotify"])
        for rule_id in (
            "universal.metadata.isrc_present",
            "universal.metadata.isrc_format",
            "universal.metadata.isrc_unique",
        ):
            r = _find(results, rule_id)
            assert r is not None, f"Missing result for {rule_id}"
            assert r.status == "pass", f"{rule_id} expected pass, got {r.status}: {r.message}"

    def test_multiple_isrc_format_errors_single_check(self, engine: DSPRulesEngine):
        """all_items_match checks every ISRC — any bad one fails the rule."""
        meta = _good_meta(isrc_list=["GB-ABC-24-00001", "INVALID", "ALSO-BAD"])
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.metadata.isrc_format")
        assert fmt.status == "fail"


# ──────────────────────────────────────────────────────────────────────────────
# Artwork rule tests
# ──────────────────────────────────────────────────────────────────────────────

class TestArtworkRules:
    def test_missing_artwork_fails_resolution(self, engine: DSPRulesEngine):
        """artwork_width=0 means no artwork uploaded → minimum_resolution fails."""
        meta = _good_meta(artwork_width=0, artwork_height=0)
        results = engine.evaluate(meta, dsps=["spotify"])
        res = _find(results, "universal.artwork.minimum_resolution")
        assert res is not None
        assert res.status == "fail"

    def test_low_resolution_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=640, artwork_height=640)
        results = engine.evaluate(meta, dsps=["spotify"])
        res = _find(results, "universal.artwork.minimum_resolution")
        assert res.status == "fail"

    def test_exact_minimum_resolution_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=3000, artwork_height=3000)
        results = engine.evaluate(meta, dsps=["spotify"])
        res = _find(results, "universal.artwork.minimum_resolution")
        assert res.status == "pass"

    def test_high_resolution_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=5000, artwork_height=5000)
        results = engine.evaluate(meta, dsps=["spotify"])
        res = _find(results, "universal.artwork.minimum_resolution")
        assert res.status == "pass"

    def test_non_square_fails_must_be_square(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=3000, artwork_height=2000)
        results = engine.evaluate(meta, dsps=["spotify"])
        sq = _find(results, "universal.artwork.must_be_square")
        assert sq is not None
        assert sq.status == "fail"

    def test_square_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=3000, artwork_height=3000)
        results = engine.evaluate(meta, dsps=["spotify"])
        sq = _find(results, "universal.artwork.must_be_square")
        assert sq.status == "pass"

    def test_no_artwork_skips_square_check(self, engine: DSPRulesEngine):
        """artwork_width=0 → must_be_square uses guard condition → passes (skip guard)."""
        meta = _good_meta(artwork_width=0, artwork_height=0)
        results = engine.evaluate(meta, dsps=["spotify"])
        sq = _find(results, "universal.artwork.must_be_square")
        # 0 == 0 → True → passes (not blocking)
        assert sq.status == "pass"

    def test_cmyk_fails_apple_color_mode_rule(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_color_mode="CMYK")
        results = engine.evaluate(meta, dsps=["apple"])
        rgb = _find(results, "apple.artwork.rgb_color_space_required")
        assert rgb is not None
        assert rgb.status == "fail"

    def test_rgb_passes_apple_color_mode_rule(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_color_mode="RGB")
        results = engine.evaluate(meta, dsps=["apple"])
        rgb = _find(results, "apple.artwork.rgb_color_space_required")
        assert rgb.status == "pass"

    def test_empty_color_mode_passes_guard(self, engine: DSPRulesEngine):
        """Empty color mode means artwork not yet analyzed → guard passes."""
        meta = _good_meta(artwork_color_mode="")
        results = engine.evaluate(meta, dsps=["apple"])
        rgb = _find(results, "apple.artwork.rgb_color_space_required")
        assert rgb.status == "pass"

    def test_invalid_format_bmp_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_format="bmp")
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.artwork.format_must_be_jpeg_or_png")
        assert fmt is not None
        assert fmt.status == "fail"

    def test_jpeg_format_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_format="jpeg")
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.artwork.format_must_be_jpeg_or_png")
        assert fmt.status == "pass"

    def test_png_format_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_format="png")
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.artwork.format_must_be_jpeg_or_png")
        assert fmt.status == "pass"

    def test_empty_format_passes_guard(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_format="")
        results = engine.evaluate(meta, dsps=["spotify"])
        fmt = _find(results, "universal.artwork.format_must_be_jpeg_or_png")
        assert fmt.status == "pass"

    def test_fix_hint_populated_on_fail(self, engine: DSPRulesEngine):
        meta = _good_meta(artwork_width=640, artwork_height=640)
        results = engine.evaluate(meta, dsps=["spotify"])
        res = _find(results, "universal.artwork.minimum_resolution")
        assert res.fix_hint is not None
        assert len(res.fix_hint) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Publisher rule tests
# ──────────────────────────────────────────────────────────────────────────────

class TestPublisherRules:
    def test_missing_publisher_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub is not None
        assert pub.status == "fail"
        assert pub.severity == "critical"

    def test_publisher_present_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="My Publishing Co.")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub.status == "pass"

    def test_whitespace_only_publisher_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="   ")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub.status == "fail"

    def test_fix_hint_on_publisher_fail(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub.fix_hint is not None

    def test_publisher_not_checked_for_youtube(self, engine: DSPRulesEngine):
        """Publisher check is Spotify-specific; shouldn't appear in YouTube results."""
        meta = _good_meta(publisher="")
        results = engine.evaluate(meta, dsps=["youtube"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub is None


# ──────────────────────────────────────────────────────────────────────────────
# Genre rule tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGenreRules:
    def test_missing_genre_fails(self, engine: DSPRulesEngine):
        meta = _good_meta(genre="")
        results = engine.evaluate(meta, dsps=["spotify"])
        genre_result = _find(results, "universal.metadata.genre_required")
        assert genre_result is not None
        assert genre_result.status == "fail"
        assert genre_result.severity == "warning"

    def test_genre_present_passes(self, engine: DSPRulesEngine):
        meta = _good_meta(genre="Electronic")
        results = engine.evaluate(meta, dsps=["spotify"])
        genre_result = _find(results, "universal.metadata.genre_required")
        assert genre_result.status == "pass"

    def test_genre_checked_for_all_dsps(self, engine: DSPRulesEngine):
        """Genre is universal — appears for every DSP."""
        meta = _good_meta(genre="")
        for dsp in ["spotify", "apple", "youtube", "amazon", "tiktok"]:
            results = engine.evaluate(meta, dsps=[dsp])
            genre_result = _find(results, "universal.metadata.genre_required")
            assert genre_result is not None, f"genre rule missing for dsp={dsp}"
            assert genre_result.status == "fail"


# ──────────────────────────────────────────────────────────────────────────────
# Explicit content flag tests
# ──────────────────────────────────────────────────────────────────────────────

class TestExplicitContentRules:
    VALID_VALUES = ["Explicit", "NotExplicit", "Clean"]

    def test_missing_parental_warning_fails_spotify(self, engine: DSPRulesEngine):
        meta = _good_meta(parental_warning="")
        results = engine.evaluate(meta, dsps=["spotify"])
        flag = _find(results, "spotify.metadata.explicit_content_flag")
        assert flag is not None
        assert flag.status == "fail"
        assert flag.severity == "critical"

    @pytest.mark.parametrize("value", VALID_VALUES)
    def test_valid_explicit_values_pass_spotify(self, engine: DSPRulesEngine, value: str):
        meta = _good_meta(parental_warning=value)
        results = engine.evaluate(meta, dsps=["spotify"])
        flag = _find(results, "spotify.metadata.explicit_content_flag")
        assert flag.status == "pass", f"Expected pass for '{value}', got {flag.status}"

    @pytest.mark.parametrize("value", ["Yes", "No", "1", "true", "explicit", "EXPLICIT"])
    def test_invalid_explicit_values_fail_valid_value_rule(
        self, engine: DSPRulesEngine, value: str
    ):
        meta = _good_meta(parental_warning=value)
        results = engine.evaluate(meta, dsps=["spotify"])
        flag = _find(results, "spotify.metadata.explicit_flag_valid_value")
        assert flag is not None
        assert flag.status == "fail", f"Expected fail for '{value}', got {flag.status}"

    def test_explicit_flag_presence_passes_valid_value_check(self, engine: DSPRulesEngine):
        """When the value IS in the valid set, valid_value rule passes."""
        meta = _good_meta(parental_warning="Explicit")
        results = engine.evaluate(meta, dsps=["spotify"])
        flag = _find(results, "spotify.metadata.explicit_flag_valid_value")
        assert flag.status == "pass"

    # Apple advisory rating
    def test_missing_advisory_fails_apple(self, engine: DSPRulesEngine):
        meta = _good_meta(parental_warning="")
        results = engine.evaluate(meta, dsps=["apple"])
        flag = _find(results, "apple.metadata.advisory_rating_required")
        assert flag is not None
        assert flag.status == "fail"

    @pytest.mark.parametrize("value", ["Explicit", "Clean", "NotExplicit", "Not Explicit"])
    def test_valid_apple_advisory_passes(self, engine: DSPRulesEngine, value: str):
        meta = _good_meta(parental_warning=value)
        results = engine.evaluate(meta, dsps=["apple"])
        flag = _find(results, "apple.metadata.advisory_rating_valid_value")
        assert flag is not None
        assert flag.status == "pass", f"Expected pass for '{value}'"

    @pytest.mark.parametrize("value", ["yes", "no", "1", "true", "EXPLICIT"])
    def test_invalid_apple_advisory_fails(self, engine: DSPRulesEngine, value: str):
        meta = _good_meta(parental_warning=value)
        results = engine.evaluate(meta, dsps=["apple"])
        flag = _find(results, "apple.metadata.advisory_rating_valid_value")
        assert flag.status == "fail"

    # TikTok explicit check
    def test_missing_explicit_fails_tiktok(self, engine: DSPRulesEngine):
        meta = _good_meta(parental_warning="")
        results = engine.evaluate(meta, dsps=["tiktok"])
        flag = _find(results, "tiktok.metadata.explicit_flag_required")
        assert flag is not None
        assert flag.status == "fail"

    def test_explicit_flag_present_passes_tiktok(self, engine: DSPRulesEngine):
        meta = _good_meta(parental_warning="Explicit")
        results = engine.evaluate(meta, dsps=["tiktok"])
        flag = _find(results, "tiktok.metadata.explicit_flag_required")
        assert flag.status == "pass"


# ──────────────────────────────────────────────────────────────────────────────
# evaluate() DSP targeting tests
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateDSPTargeting:
    def test_spotify_only_excludes_apple_rules(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify"])
        rule_ids = {r.rule_id for r in results}
        assert not any(rid.startswith("apple.") for rid in rule_ids)

    def test_apple_only_excludes_spotify_rules(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["apple"])
        rule_ids = {r.rule_id for r in results}
        assert not any(rid.startswith("spotify.") for rid in rule_ids)

    def test_spotify_includes_universal_rules(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify"])
        rule_ids = {r.rule_id for r in results}
        assert any(rid.startswith("universal.") for rid in rule_ids)

    def test_empty_dsps_returns_universal_only(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=[])
        for r in results:
            rule = engine.get_rule(r.rule_id)
            assert rule is not None
            assert rule.dsp is None, f"Expected universal rule but got {r.rule_id} (dsp={rule.dsp})"

    def test_default_dsps_include_all_platforms(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta)  # uses default dsps
        rule_ids = {r.rule_id for r in results}
        assert any(rid.startswith("spotify.") for rid in rule_ids)
        assert any(rid.startswith("apple.") for rid in rule_ids)
        assert any(rid.startswith("youtube.") for rid in rule_ids)
        assert any(rid.startswith("amazon.") for rid in rule_ids)
        assert any(rid.startswith("tiktok.") for rid in rule_ids)
        assert any(rid.startswith("universal.") for rid in rule_ids)

    def test_multi_dsp_includes_both(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify", "apple"])
        rule_ids = {r.rule_id for r in results}
        assert any(rid.startswith("spotify.") for rid in rule_ids)
        assert any(rid.startswith("apple.") for rid in rule_ids)
        assert not any(rid.startswith("youtube.") for rid in rule_ids)


# ──────────────────────────────────────────────────────────────────────────────
# RuleResult structure tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRuleResultStructure:
    def test_status_values_are_valid(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify"])
        for r in results:
            assert r.status in {"pass", "fail", "skip"}, \
                f"{r.rule_id}: unexpected status {r.status!r}"

    def test_severity_mirrors_rule(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub is not None
        rule = engine.get_rule("spotify.metadata.contributor_publisher_required")
        assert pub.severity == rule.severity

    def test_fix_hint_none_on_pass(self, engine: DSPRulesEngine):
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify"])
        for r in results:
            if r.status == "pass":
                assert r.fix_hint is None, \
                    f"{r.rule_id}: fix_hint should be None on pass, got {r.fix_hint!r}"

    def test_fix_hint_populated_on_fail(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        assert pub.status == "fail"
        assert pub.fix_hint is not None

    def test_checked_value_reflects_field(self, engine: DSPRulesEngine):
        meta = _good_meta(publisher="My Publisher")
        results = engine.evaluate(meta, dsps=["spotify"])
        pub = _find(results, "spotify.metadata.contributor_publisher_required")
        # checked_value should reflect the publisher field (or isrc_list, etc.)
        # just verify it's not None for a rule that has a field access
        assert pub.checked_value is not None

    def test_skip_status_for_rules_without_check(self, engine: DSPRulesEngine):
        """Rules with check=null should return status='skip'."""
        meta = _good_meta()
        results = engine.evaluate(meta, dsps=["spotify", "apple"])
        skipped = [r for r in results if r.status == "skip"]
        # spotify.artwork.no_spotify_logo and apple.artwork.no_apple_logo have no check
        assert len(skipped) > 0


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_rule() direct tests
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateRuleDirect:
    def test_rule_with_no_check_returns_skip(self, engine: DSPRulesEngine):
        rule = RuleDefinition(
            id="test.skip",
            layer="metadata",
            dsp="spotify",
            title="No check rule",
            severity="warning",
            category="test",
            check=None,
        )
        meta = _good_meta()
        result = engine.evaluate_rule(rule, meta)
        assert result.status == "skip"

    def test_passing_rule(self, engine: DSPRulesEngine):
        rule = RuleDefinition(
            id="test.pass",
            layer="metadata",
            dsp=None,
            title="Title check",
            severity="critical",
            category="test",
            check="has_value(metadata.title)",
        )
        meta = _good_meta(title="My Release")
        result = engine.evaluate_rule(rule, meta)
        assert result.status == "pass"
        assert result.fix_hint is None

    def test_failing_rule(self, engine: DSPRulesEngine):
        rule = RuleDefinition(
            id="test.fail",
            layer="metadata",
            dsp=None,
            title="Title check",
            severity="critical",
            category="test",
            fix_hint="Add a title.",
            check="has_value(metadata.title)",
        )
        meta = _good_meta(title="")
        result = engine.evaluate_rule(rule, meta)
        assert result.status == "fail"
        assert result.fix_hint == "Add a title."

    def test_eval_error_returns_fail_not_exception(self, engine: DSPRulesEngine):
        """Bad expressions must never propagate as exceptions."""
        rule = RuleDefinition(
            id="test.bad_expr",
            layer="metadata",
            dsp=None,
            title="Bad expression rule",
            severity="info",
            category="test",
            check="open('/etc/passwd')",  # disallowed
        )
        meta = _good_meta()
        result = engine.evaluate_rule(rule, meta)
        assert result.status == "fail"
        assert "error" in result.message.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find(results: list[RuleResult], rule_id: str) -> RuleResult | None:
    """Find a result by rule_id, or return None."""
    for r in results:
        if r.rule_id == rule_id:
            return r
    return None
