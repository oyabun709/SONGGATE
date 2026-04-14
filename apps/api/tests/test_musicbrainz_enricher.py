"""
Tests for services/enrichment/musicbrainz.py

All MusicBrainz API calls are mocked — no real network calls.
We verify the enrichment logic: suggestion generation, deduplication,
ISRC format validation, mismatch detection, fallback search.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure apps/api is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub musicbrainzngs before importing the service so it doesn't need to be installed
import types

mb_stub = types.ModuleType("musicbrainzngs")
mb_stub.set_useragent = lambda *a, **kw: None
mb_stub.set_rate_limit = lambda *a, **kw: None
mb_stub.ResponseError = type("ResponseError", (Exception,), {})
mb_stub.NetworkError = type("NetworkError", (Exception,), {})
mb_stub.get_recordings_by_isrc = MagicMock()
mb_stub.get_release_by_id = MagicMock()
mb_stub.search_recordings = MagicMock()
sys.modules["musicbrainzngs"] = mb_stub

from services.enrichment.musicbrainz import (
    MusicBrainzEnricher,
    EnrichmentResult,
    EnrichmentSuggestion,
    ISRCValidationResult,
    _normalize_isrc,
    _is_valid_isrc_format,
    _flatten_artist_credits,
    _similarity,
)
from services.metadata.rules_engine import ReleaseMetadata


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _meta(**kwargs) -> ReleaseMetadata:
    defaults = {
        "title": "Midnight Drive",
        "artist": "Test Artist",
        "isrc_list": [],
        "composers": [],
        "iswc": "",
        "label": "",
        "genre": "",
    }
    defaults.update(kwargs)
    return ReleaseMetadata(**defaults)


def _make_recording(
    rec_id: str = "rec-001",
    title: str = "Midnight Drive",
    artist: str = "Test Artist",
    tags: list[str] | None = None,
    work_rels: list[dict] | None = None,
    releases: list[dict] | None = None,
) -> dict:
    artist_credit = [{"artist": {"name": artist}, "joinphrase": ""}]
    tag_list = [{"name": t} for t in (tags or [])]
    return {
        "id": rec_id,
        "title": title,
        "artist-credit": artist_credit,
        "tag-list": tag_list,
        "relation-list": work_rels or [],
        "release-list": releases or [],
    }


def _isrc_response(recordings: list[dict]) -> dict:
    return {"isrc": {"recording-list": recordings}}


def _not_found_404():
    exc = mb_stub.ResponseError("404")
    exc.args = ("404",)
    return exc


# ──────────────────────────────────────────────────────────────────────────────
# ISRC format validation helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestISRCHelpers(unittest.TestCase):

    def test_normalize_strips_hyphens(self):
        self.assertEqual(_normalize_isrc("US-RC1-23-45678"), "USRC12345678")

    def test_normalize_uppercases(self):
        self.assertEqual(_normalize_isrc("usrc12345678"), "USRC12345678")

    def test_valid_isrc_no_hyphens(self):
        self.assertTrue(_is_valid_isrc_format("USRC12345678"))

    def test_valid_isrc_with_hyphens_normalized(self):
        # normalize first
        self.assertTrue(_is_valid_isrc_format(_normalize_isrc("US-RC1-23-45678")))

    def test_too_short(self):
        self.assertFalse(_is_valid_isrc_format("USRC123456"))

    def test_too_long(self):
        self.assertFalse(_is_valid_isrc_format("USRC12345678X"))

    def test_lowercase_fails_before_normalize(self):
        self.assertFalse(_is_valid_isrc_format("usrc12345678"))

    def test_digits_in_country_code_fails(self):
        # Country code must be 2 alpha chars
        self.assertFalse(_is_valid_isrc_format("12RC12345678"))


# ──────────────────────────────────────────────────────────────────────────────
# _flatten_artist_credits
# ──────────────────────────────────────────────────────────────────────────────

class TestFlattenArtistCredits(unittest.TestCase):

    def test_single_artist(self):
        credits = [{"artist": {"name": "Adele"}, "joinphrase": ""}]
        self.assertEqual(_flatten_artist_credits(credits), "Adele")

    def test_feat_artist(self):
        credits = [
            {"artist": {"name": "Drake"}, "joinphrase": " feat. "},
            {"artist": {"name": "Future"}, "joinphrase": ""},
        ]
        self.assertEqual(_flatten_artist_credits(credits), "Drake feat. Future")

    def test_empty_credits(self):
        self.assertEqual(_flatten_artist_credits([]), "")

    def test_string_join_phrase(self):
        credits = [{"artist": {"name": "A"}, "joinphrase": " & "}, {"artist": {"name": "B"}, "joinphrase": ""}]
        self.assertEqual(_flatten_artist_credits(credits), "A & B")


# ──────────────────────────────────────────────────────────────────────────────
# _similarity
# ──────────────────────────────────────────────────────────────────────────────

class TestSimilarity(unittest.TestCase):

    def test_identical(self):
        self.assertAlmostEqual(_similarity("hello", "hello"), 1.0)

    def test_empty_strings(self):
        self.assertEqual(_similarity("", "anything"), 0.0)

    def test_completely_different(self):
        self.assertLess(_similarity("abc", "xyz"), 0.5)

    def test_case_insensitive(self):
        self.assertAlmostEqual(_similarity("Test Artist", "test artist"), 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# validate_isrc
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateISRC(unittest.TestCase):

    def setUp(self):
        self.enricher = MusicBrainzEnricher()
        mb_stub.get_recordings_by_isrc.reset_mock()

    def test_invalid_format_returns_early(self):
        result = self.enricher.validate_isrc("BAD-ISRC")
        self.assertFalse(result.format_valid)
        self.assertFalse(result.exists_in_mb)
        mb_stub.get_recordings_by_isrc.assert_not_called()

    def test_valid_format_flag(self):
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([])
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertTrue(result.format_valid)

    def test_not_found_in_mb(self):
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([])
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertFalse(result.exists_in_mb)

    def test_found_in_mb(self):
        rec = _make_recording("rec-001", "Midnight Drive", "Test Artist")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertTrue(result.exists_in_mb)
        self.assertEqual(result.mb_recording_id, "rec-001")
        self.assertEqual(result.mb_recording_title, "Midnight Drive")
        self.assertEqual(result.mb_artist_name, "Test Artist")

    def test_mb_url_set_when_found(self):
        rec = _make_recording("rec-abc")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertIn("rec-abc", result.mb_url)
        self.assertIn("musicbrainz.org", result.mb_url)

    def test_no_mismatch_when_titles_match(self):
        rec = _make_recording("rec-001", "Midnight Drive", "Test Artist")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc(
            "USRC12345678",
            expected_title="Midnight Drive",
            expected_artist="Test Artist",
        )
        self.assertFalse(result.has_mismatch)
        self.assertEqual(result.mismatch_details, [])

    def test_title_mismatch_detected(self):
        rec = _make_recording("rec-001", "Totally Different Song", "Test Artist")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc(
            "USRC12345678",
            expected_title="Midnight Drive",
        )
        self.assertTrue(result.has_mismatch)
        self.assertTrue(len(result.mismatch_details) > 0)
        self.assertIn("Title mismatch", result.mismatch_details[0])

    def test_artist_mismatch_detected(self):
        rec = _make_recording("rec-001", "Midnight Drive", "Completely Different Artist")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc(
            "USRC12345678",
            expected_artist="Test Artist",
        )
        self.assertTrue(result.has_mismatch)
        self.assertTrue(any("Artist mismatch" in d for d in result.mismatch_details))

    def test_404_response_means_not_found(self):
        mb_stub.get_recordings_by_isrc.side_effect = mb_stub.ResponseError("404 not found")
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertFalse(result.exists_in_mb)
        self.assertEqual(result.errors, [])  # 404 is not an error

    def test_network_error_captured(self):
        mb_stub.get_recordings_by_isrc.side_effect = mb_stub.NetworkError("timeout")
        result = self.enricher.validate_isrc("USRC12345678")
        self.assertTrue(any("network" in e.lower() for e in result.errors))

    def test_isrc_with_hyphens_normalized(self):
        rec = _make_recording()
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        result = self.enricher.validate_isrc("US-RC1-23-45678")
        # Should work — format validation normalizes before checking
        call_args = mb_stub.get_recordings_by_isrc.call_args
        self.assertEqual(call_args[0][0], "USRC12345678")


# ──────────────────────────────────────────────────────────────────────────────
# enrich_release — ISRC path
# ──────────────────────────────────────────────────────────────────────────────

class TestEnrichReleaseISRCPath(unittest.TestCase):

    def setUp(self):
        self.enricher = MusicBrainzEnricher()
        mb_stub.get_recordings_by_isrc.reset_mock(side_effect=True, return_value=True)
        mb_stub.get_release_by_id.reset_mock(side_effect=True, return_value=True)
        mb_stub.search_recordings.reset_mock(side_effect=True, return_value=True)
        mb_stub.get_recordings_by_isrc.side_effect = None
        mb_stub.get_release_by_id.side_effect = None
        mb_stub.search_recordings.side_effect = None

    def test_no_isrcs_falls_through_to_search(self):
        mb_stub.search_recordings.return_value = {"recording-list": []}
        meta = _meta(title="My Song", artist="My Artist", isrc_list=[])
        result = self.enricher.enrich_release(meta)
        mb_stub.get_recordings_by_isrc.assert_not_called()
        mb_stub.search_recordings.assert_called_once()

    def test_invalid_isrc_skipped(self):
        mb_stub.search_recordings.return_value = {"recording-list": []}
        meta = _meta(isrc_list=["INVALID"])
        self.enricher.enrich_release(meta)
        mb_stub.get_recordings_by_isrc.assert_not_called()

    def test_valid_isrc_triggers_lookup(self):
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([])
        meta = _meta(isrc_list=["USRC12345678"])
        self.enricher.enrich_release(meta)
        mb_stub.get_recordings_by_isrc.assert_called_once()

    def test_recording_id_collected(self):
        rec = _make_recording("rec-001")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678"])
        result = self.enricher.enrich_release(meta)
        self.assertIn("rec-001", result.mb_recording_ids)

    def test_genre_tags_collected(self):
        rec = _make_recording("rec-001", tags=["pop", "electronic"])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678"])
        result = self.enricher.enrich_release(meta)
        self.assertIn("pop", result.genres)
        self.assertIn("electronic", result.genres)

    def test_genres_deduplicated(self):
        rec1 = _make_recording("rec-001", tags=["pop"])
        rec2 = _make_recording("rec-002", tags=["pop", "rock"])
        # Two ISRCs — second response must also be handled
        mb_stub.get_recordings_by_isrc.side_effect = [
            _isrc_response([rec1]),
            _isrc_response([rec2]),
        ]
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678", "GBRC12345679"])
        result = self.enricher.enrich_release(meta)
        self.assertEqual(result.genres.count("pop"), 1)

    def test_iswc_suggestion_when_not_set(self):
        work = {"id": "work-001", "iswc": "T-123.456.789-0", "relation-list": []}
        work_rel = {
            "target-type": "work",
            "relation": [{"work": work}],
        }
        rec = _make_recording("rec-001", work_rels=[work_rel])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678"], iswc="")
        result = self.enricher.enrich_release(meta)
        self.assertEqual(result.iswc, "T-123.456.789-0")
        iswc_suggestion = next(
            (s for s in result.suggestions if s.field == "iswc"), None
        )
        self.assertIsNotNone(iswc_suggestion)
        self.assertIn("T-123.456.789-0", iswc_suggestion.message)
        self.assertEqual(iswc_suggestion.confidence, "high")

    def test_no_iswc_suggestion_when_already_set(self):
        work = {"id": "work-001", "iswc": "T-123.456.789-0", "relation-list": []}
        work_rel = {"target-type": "work", "relation": [{"work": work}]}
        rec = _make_recording("rec-001", work_rels=[work_rel])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678"], iswc="T-123.456.789-0")
        result = self.enricher.enrich_release(meta)
        iswc_suggestions = [s for s in result.suggestions if s.field == "iswc"]
        self.assertEqual(iswc_suggestions, [])

    def test_composer_suggestion_generated(self):
        composer_rel = {
            "type": "composer",
            "artist": {"name": "Jane Songwriter"},
        }
        work = {
            "id": "work-001",
            "relation-list": [{"relation": [composer_rel]}],
        }
        work_rel = {"target-type": "work", "relation": [{"work": work}]}
        rec = _make_recording("rec-001", work_rels=[work_rel])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        meta = _meta(isrc_list=["USRC12345678"], composers=[])
        result = self.enricher.enrich_release(meta)
        self.assertIn("Jane Songwriter", result.composers)
        comp_suggestion = next((s for s in result.suggestions if s.field == "composers"), None)
        self.assertIsNotNone(comp_suggestion)
        self.assertIn("Jane Songwriter", comp_suggestion.message)

    def test_label_suggestion_when_not_set(self):
        rec = _make_recording("rec-001", releases=[{"id": "rel-001"}])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {
            "release": {
                "label-info-list": [
                    {"label": {"name": "Big Label Records"}}
                ]
            }
        }
        meta = _meta(isrc_list=["USRC12345678"], label="")
        result = self.enricher.enrich_release(meta)
        self.assertEqual(result.label, "Big Label Records")
        label_suggestion = next((s for s in result.suggestions if s.field == "label"), None)
        self.assertIsNotNone(label_suggestion)
        self.assertIn("Big Label Records", label_suggestion.message)

    def test_label_mismatch_suggestion_low_confidence(self):
        rec = _make_recording("rec-001", releases=[{"id": "rel-001"}])
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {
            "release": {
                "label-info-list": [{"label": {"name": "Completely Different Label"}}]
            }
        }
        meta = _meta(isrc_list=["USRC12345678"], label="My Own Label")
        result = self.enricher.enrich_release(meta)
        label_suggestion = next(
            (s for s in result.suggestions if s.field == "label"), None
        )
        self.assertIsNotNone(label_suggestion)
        self.assertEqual(label_suggestion.confidence, "low")

    def test_404_isrc_not_error(self):
        mb_stub.get_recordings_by_isrc.side_effect = mb_stub.ResponseError("404 not found")
        meta = _meta(isrc_list=["USRC12345678"])
        result = self.enricher.enrich_release(meta)
        self.assertEqual(result.errors, [])

    def test_network_error_recorded(self):
        mb_stub.get_recordings_by_isrc.side_effect = mb_stub.NetworkError("timeout")
        meta = _meta(isrc_list=["USRC12345678"])
        result = self.enricher.enrich_release(meta)
        self.assertTrue(any("network" in e.lower() for e in result.errors))

    def test_lookup_duration_set(self):
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([])
        meta = _meta(isrc_list=["USRC12345678"])
        result = self.enricher.enrich_release(meta)
        self.assertIsNotNone(result.lookup_duration_seconds)
        self.assertGreaterEqual(result.lookup_duration_seconds, 0)


# ──────────────────────────────────────────────────────────────────────────────
# enrich_release — fallback text search
# ──────────────────────────────────────────────────────────────────────────────

class TestEnrichReleaseFallbackSearch(unittest.TestCase):

    def setUp(self):
        self.enricher = MusicBrainzEnricher()
        mb_stub.get_recordings_by_isrc.reset_mock(side_effect=True, return_value=True)
        mb_stub.search_recordings.reset_mock(side_effect=True, return_value=True)
        mb_stub.get_recordings_by_isrc.side_effect = None
        mb_stub.search_recordings.side_effect = None

    def test_search_called_when_no_isrcs(self):
        mb_stub.search_recordings.return_value = {"recording-list": []}
        meta = _meta(isrc_list=[])
        self.enricher.enrich_release(meta)
        mb_stub.search_recordings.assert_called_once()

    def test_search_uses_title_and_artist(self):
        mb_stub.search_recordings.return_value = {"recording-list": []}
        meta = _meta(title="Midnight Drive", artist="Test Artist", isrc_list=[])
        self.enricher.enrich_release(meta)
        call_kwargs = mb_stub.search_recordings.call_args[1]
        self.assertEqual(call_kwargs.get("recording"), "Midnight Drive")
        self.assertEqual(call_kwargs.get("artist"), "Test Artist")

    def test_good_search_match_collects_genres(self):
        rec = _make_recording("rec-001", "Midnight Drive", "Test Artist", tags=["indie"])
        mb_stub.search_recordings.return_value = {"recording-list": [rec]}
        meta = _meta(isrc_list=[])
        result = self.enricher.enrich_release(meta)
        self.assertIn("indie", result.genres)

    def test_low_similarity_match_ignored(self):
        rec = _make_recording("rec-001", "Totally Unrelated Track", "Nobody Famous")
        mb_stub.search_recordings.return_value = {"recording-list": [rec]}
        meta = _meta(title="Midnight Drive", artist="Test Artist", isrc_list=[])
        result = self.enricher.enrich_release(meta)
        # Low-similarity result should not produce recording IDs or suggestions
        self.assertEqual(result.mb_recording_ids, [])

    def test_genre_suggestion_when_no_genre_set(self):
        rec = _make_recording("rec-001", "Midnight Drive", "Test Artist", tags=["pop"])
        mb_stub.search_recordings.return_value = {"recording-list": [rec]}
        meta = _meta(title="Midnight Drive", artist="Test Artist", isrc_list=[], genre="")
        result = self.enricher.enrich_release(meta)
        genre_suggestion = next((s for s in result.suggestions if s.field == "genre"), None)
        self.assertIsNotNone(genre_suggestion)
        self.assertIn("pop", genre_suggestion.message)

    def test_no_search_when_isrc_already_found_results(self):
        """If ISRC lookup succeeds, fallback search should not run."""
        rec = _make_recording("rec-001")
        mb_stub.get_recordings_by_isrc.return_value = _isrc_response([rec])
        mb_stub.get_release_by_id.return_value = {"release": {"label-info-list": []}}
        mb_stub.search_recordings.return_value = {"recording-list": []}
        meta = _meta(isrc_list=["USRC12345678"])
        self.enricher.enrich_release(meta)
        mb_stub.search_recordings.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# EnrichmentResult.to_dict()
# ──────────────────────────────────────────────────────────────────────────────

class TestEnrichmentResultToDict(unittest.TestCase):

    def test_to_dict_keys(self):
        result = EnrichmentResult(
            mb_recording_ids=["rec-001"],
            composers=["Jane"],
            iswc="T-123",
            suggestions=[
                EnrichmentSuggestion(
                    field="iswc",
                    suggested="T-123",
                    current="",
                    source_url="https://musicbrainz.org/work/w-1",
                    message="ISWC found",
                )
            ],
        )
        d = result.to_dict()
        for key in ("mb_recording_ids", "mb_release_ids", "composers", "publisher",
                    "label", "iswc", "genres", "suggestions", "errors"):
            self.assertIn(key, d)

    def test_to_dict_suggestion_keys(self):
        result = EnrichmentResult(
            suggestions=[
                EnrichmentSuggestion(
                    field="iswc",
                    suggested="T-123",
                    current="",
                    source_url="https://example.com",
                    message="Found",
                    confidence="high",
                    mb_entity_id="w-001",
                )
            ]
        )
        d = result.to_dict()
        s = d["suggestions"][0]
        for key in ("field", "suggested", "current", "source_url", "message", "confidence", "mb_entity_id"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
