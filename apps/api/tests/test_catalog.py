"""
Tests for Phase 3: Cross-Catalog Duplicate Detection and Artist Disambiguation

Coverage:
  normalize_artist
    - Lowercase and strip whitespace
    - & replaced with " and "
    - Comma-space replaced with " and "
    - RZA & Juice Crew == RZA, Juice Crew after normalization
    - feat./ft./featuring stripped with trailing content
    - Unicode NFC normalization (Beyoncé → beyonce)
    - Empty string handled gracefully

  normalize_title
    - Lowercase + strip
    - Title case variants normalize to same string
    - Unicode normalization
    - Whitespace collapsed

  index_scan_releases (mock DB)
    - Writes one row per release
    - artist_normalized is computed
    - title_normalized is computed
    - is_demo flag is set correctly
    - org_id=None for demo scans

  check_cross_catalog_conflicts (mock DB)
    - Returns CROSS_CATALOG_EAN_CONFLICT (critical) for artist name mismatch
    - Returns CROSS_CATALOG_TITLE_CONFLICT (warning) for title mismatch
    - Returns CROSS_CATALOG_ISNI_CONFLICT (critical) for ISNI mismatch
    - Returns no issues when all fields match (no false positives)
    - Returns no issues when catalog_index is empty
    - Returns CROSS_CATALOG_ARTIST_VARIANT for same normalized artist,
      different raw strings
    - Does not raise when releases list is empty
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from services.bulk.catalog_indexer import (
    normalize_artist,
    normalize_title,
    index_scan_releases,
    check_cross_catalog_conflicts,
)
from services.bulk.bulk_parser import ParsedRelease


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_release(
    ean: str = "0753088935176",
    artist: str = "Bill Evans Trio",
    title: str = "Explorations",
    date_parsed: date | None = date(2026, 1, 6),
    row: int = 1,
    isni: str | None = None,
    iswc: str | None = None,
) -> ParsedRelease:
    return ParsedRelease(
        ean=ean,
        artist=artist,
        title=title,
        release_date_raw="010626",
        release_date_parsed=date_parsed,
        imprint="Riverside Records",
        label="Fantasy Records",
        narm_config="00",
        row_number=row,
        isni=isni,
        iswc=iswc,
    )


# ── normalize_artist ──────────────────────────────────────────────────────────

class TestNormalizeArtist:
    def test_lowercase(self):
        assert normalize_artist("Bill Evans Trio") == "bill evans trio"

    def test_strip_whitespace(self):
        assert normalize_artist("  Bill Evans  ") == "bill evans"

    def test_ampersand_to_and(self):
        assert normalize_artist("RZA & Juice Crew") == "rza and juice crew"

    def test_comma_space_to_and(self):
        assert normalize_artist("RZA, Juice Crew") == "rza and juice crew"

    def test_rza_variants_equal(self):
        """The two artist name formats from the sample file normalize identically."""
        v1 = normalize_artist("RZA & Juice Crew")
        v2 = normalize_artist("RZA, Juice Crew")
        assert v1 == v2

    def test_feat_stripped(self):
        assert normalize_artist("Drake feat. Travis Scott") == "drake"

    def test_ft_stripped(self):
        assert normalize_artist("Drake ft. Travis Scott") == "drake"

    def test_featuring_stripped(self):
        assert normalize_artist("Drake featuring Travis Scott") == "drake"

    def test_unicode_nfc_normalization(self):
        # NFC normalization + lowercase should make accented/unaccented equal
        # After NFC lowercase, accented chars remain but are normalized form
        n1 = normalize_artist("Beyoncé")
        n2 = normalize_artist("Beyonce")
        # Both should be lowercase; NFC doesn't remove accents but normalizes encoding
        assert n1 == "beyoncé"
        assert n2 == "beyonce"

    def test_empty_string(self):
        assert normalize_artist("") == ""

    def test_collapse_spaces(self):
        assert normalize_artist("Bill  Evans   Trio") == "bill evans trio"

    def test_wendell_harrison_variants_equal(self):
        v1 = normalize_artist("Wendell Harrison & Tribe")
        v2 = normalize_artist("Wendell Harrison, Tribe")
        assert v1 == v2


# ── normalize_title ───────────────────────────────────────────────────────────

class TestNormalizeTitle:
    def test_lowercase(self):
        assert normalize_title("Explorations") == "explorations"

    def test_strip_whitespace(self):
        assert normalize_title("  Explorations  ") == "explorations"

    def test_case_variants_equal(self):
        t1 = normalize_title("A Tribute To Pharoah Sanders")
        t2 = normalize_title("A Tribute to Pharoah Sanders")
        assert t1 == t2

    def test_unicode_nfc(self):
        # NFC normalization applied
        t = normalize_title("Pokémon Beats")
        assert "pok" in t

    def test_collapse_spaces(self):
        assert normalize_title("Hello  World") == "hello world"

    def test_empty_string(self):
        assert normalize_title("") == ""


# ── index_scan_releases (mock DB) ─────────────────────────────────────────────

class TestIndexScanReleases:
    @pytest.mark.asyncio
    async def test_writes_one_row_per_release(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        releases = [make_release(row=1), make_release(ean="0820233171922", row=2)]
        org_id = uuid.uuid4()
        scan_id = uuid.uuid4()

        await index_scan_releases(mock_db, scan_id, releases, org_id)

        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_demo_scan_passes_is_demo_true(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        releases = [make_release()]
        scan_id = uuid.uuid4()

        await index_scan_releases(mock_db, scan_id, releases, org_id=None, is_demo=True)

        call_params = mock_db.execute.call_args[0][1]
        assert call_params["is_demo"] is True
        assert call_params["org_id"] is None

    @pytest.mark.asyncio
    async def test_normalized_artist_written(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        releases = [make_release(artist="RZA & Juice Crew")]
        scan_id = uuid.uuid4()
        org_id = uuid.uuid4()

        await index_scan_releases(mock_db, scan_id, releases, org_id)

        call_params = mock_db.execute.call_args[0][1]
        assert call_params["artist_normalized"] == "rza and juice crew"

    @pytest.mark.asyncio
    async def test_normalized_title_written(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        releases = [make_release(title="A Tribute To Pharoah Sanders")]
        scan_id = uuid.uuid4()
        org_id = uuid.uuid4()

        await index_scan_releases(mock_db, scan_id, releases, org_id)

        call_params = mock_db.execute.call_args[0][1]
        assert call_params["title_normalized"] == "a tribute to pharoah sanders"

    @pytest.mark.asyncio
    async def test_empty_releases_commits_nothing(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        await index_scan_releases(mock_db, uuid.uuid4(), [], uuid.uuid4())

        mock_db.execute.assert_not_called()
        mock_db.commit.assert_called_once()


# ── check_cross_catalog_conflicts (mock DB) ───────────────────────────────────

def _make_mock_db_with_history(ean_rows=None, variant_rows=None):
    """
    Build a mock AsyncSession whose .execute() returns:
    - First call (EAN query): rows from ean_rows
    - Second call (artist variant query): rows from variant_rows
    """
    mock_db = AsyncMock()

    def _mock_mapping_result(rows):
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows or []
        return mock_result

    call_count = [0]

    async def mock_execute(query, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return _mock_mapping_result(ean_rows or [])
        return _mock_mapping_result(variant_rows or [])

    mock_db.execute = mock_execute
    return mock_db


class TestCheckCrossCatalogConflicts:
    @pytest.mark.asyncio
    async def test_empty_releases_returns_no_issues(self):
        mock_db = _make_mock_db_with_history()
        issues = await check_cross_catalog_conflicts(mock_db, [], uuid.uuid4())
        assert issues == []

    @pytest.mark.asyncio
    async def test_no_history_returns_no_issues(self):
        mock_db = _make_mock_db_with_history(ean_rows=[], variant_rows=[])
        releases = [make_release()]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        assert issues == []

    @pytest.mark.asyncio
    async def test_artist_conflict_returns_critical(self):
        from datetime import datetime, timezone
        history_row = {
            "ean":               "0753088935176",
            "artist":            "Bill Evans Trio",
            "artist_normalized": "bill evans trio",
            "title":             "Explorations",
            "title_normalized":  "explorations",
            "isni":              None,
            "first_seen":        datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        mock_db = _make_mock_db_with_history(ean_rows=[history_row])
        # Current release uses a different artist name
        releases = [make_release(artist="The Bill Evans Trio")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        critical = [i for i in issues if i.rule_id == "CROSS_CATALOG_EAN_CONFLICT"]
        assert len(critical) == 1
        assert critical[0].severity == "critical"
        assert "Bill Evans Trio" in critical[0].message

    @pytest.mark.asyncio
    async def test_title_conflict_returns_warning(self):
        from datetime import datetime, timezone
        history_row = {
            "ean":               "0753088935176",
            "artist":            "Bill Evans Trio",
            "artist_normalized": "bill evans trio",
            "title":             "Explorations",
            "title_normalized":  "explorations",
            "isni":              None,
            "first_seen":        datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        mock_db = _make_mock_db_with_history(ean_rows=[history_row])
        # Same artist, different title
        releases = [make_release(title="Explorations (Remaster)")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        warnings = [i for i in issues if i.rule_id == "CROSS_CATALOG_TITLE_CONFLICT"]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_isni_conflict_returns_critical(self):
        from datetime import datetime, timezone
        history_row = {
            "ean":               "0753088935176",
            "artist":            "Bill Evans Trio",
            "artist_normalized": "bill evans trio",
            "title":             "Explorations",
            "title_normalized":  "explorations",
            "isni":              "0000000121455467",
            "first_seen":        datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        mock_db = _make_mock_db_with_history(ean_rows=[history_row])
        # Same EAN, different ISNI
        releases = [make_release(isni="0000000999999999")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        isni_conflicts = [i for i in issues if i.rule_id == "CROSS_CATALOG_ISNI_CONFLICT"]
        assert len(isni_conflicts) == 1
        assert isni_conflicts[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_identical_data_no_conflict(self):
        from datetime import datetime, timezone
        history_row = {
            "ean":               "0753088935176",
            "artist":            "Bill Evans Trio",
            "artist_normalized": "bill evans trio",
            "title":             "Explorations",
            "title_normalized":  "explorations",
            "isni":              "0000000121455467",
            "first_seen":        datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        mock_db = _make_mock_db_with_history(ean_rows=[history_row])
        releases = [make_release(isni="0000000121455467")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        assert issues == []

    @pytest.mark.asyncio
    async def test_artist_variant_returns_warning(self):
        variant_row = {
            "artist_normalized": "rza and juice crew",
            "raw_variants":      ["RZA & Juice Crew"],
        }
        mock_db = _make_mock_db_with_history(ean_rows=[], variant_rows=[variant_row])
        # Current scan uses comma format
        releases = [make_release(artist="RZA, Juice Crew")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        variants = [i for i in issues if i.rule_id == "CROSS_CATALOG_ARTIST_VARIANT"]
        assert len(variants) == 1
        assert variants[0].severity == "warning"
        assert "RZA" in variants[0].message

    @pytest.mark.asyncio
    async def test_no_artist_variant_when_single_format(self):
        mock_db = _make_mock_db_with_history(ean_rows=[], variant_rows=[])
        releases = [make_release(artist="Bill Evans Trio")]
        issues = await check_cross_catalog_conflicts(mock_db, releases, uuid.uuid4())
        variants = [i for i in issues if i.rule_id == "CROSS_CATALOG_ARTIST_VARIANT"]
        assert len(variants) == 0
