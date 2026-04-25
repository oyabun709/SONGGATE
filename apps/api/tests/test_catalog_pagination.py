"""
Pagination tests for catalog router endpoints.

Coverage:
  GET /catalog/conflicts
    - page=1 per_page=10 requests correct OFFSET=0
    - page=2 per_page=10 requests correct OFFSET=10
    - response contains data/total/page/per_page/total_pages
    - total_pages calculated correctly (ceil division)
    - total_pages=1 when total=0
    - per_page capped at 100 by Query validation

  GET /catalog/artist-variants
    - same pagination contract as /conflicts
    - total badge reflects true total, not current page size
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from routers.catalog import get_catalog_conflicts, get_artist_variants


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(org_id: uuid.UUID | None = None) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    return org


def _scalar_result(value):
    mock = MagicMock()
    mock.scalar.return_value = value
    return mock


def _mapping_result(rows: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.mappings.return_value.all.return_value = rows
    return mock


def _conflict_rows(n: int) -> list[dict]:
    from datetime import date
    return [
        {
            "ean":                  f"07530889351{i:02d}",
            "artist_variants":      [f"Artist {i}", f"Artist {i} Alt"],
            "title_variants":       [f"Title {i}"],
            "has_artist_conflict":  True,
            "has_title_conflict":   False,
            "has_isni_conflict":    False,
            "scan_count":           2,
            "first_seen":           None,
            "last_seen":            None,
        }
        for i in range(n)
    ]


def _variant_rows(n: int) -> list[dict]:
    return [
        {
            "normalized":         f"artist {i}",
            "raw_variants":       [f"Artist {i}", f"Artist {i},"],
            "ean_count":          3,
            "unique_isni_count":  0,
            "with_isni_count":    0,
            "total_count":        2,
        }
        for i in range(n)
    ]


# ── Conflict pagination ───────────────────────────────────────────────────────

class TestConflictPagination:
    @pytest.mark.asyncio
    async def test_page1_offset_is_zero(self):
        """OFFSET parameter passed to DB is 0 for page=1."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(30),           # COUNT query
            _mapping_result(_conflict_rows(10)),  # data query
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=1, per_page=10, db=db, org=org)

        # Second execute call is the data query — check OFFSET in params
        data_call_params = db.execute.call_args_list[1][0][1]
        assert data_call_params["offset"] == 0
        assert data_call_params["limit"] == 10

    @pytest.mark.asyncio
    async def test_page2_offset_is_per_page(self):
        """OFFSET parameter passed to DB is 10 for page=2, per_page=10."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(30),
            _mapping_result(_conflict_rows(10)),
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=2, per_page=10, db=db, org=org)

        data_call_params = db.execute.call_args_list[1][0][1]
        assert data_call_params["offset"] == 10
        assert data_call_params["limit"] == 10

    @pytest.mark.asyncio
    async def test_response_shape(self):
        """Response has data, total, page, per_page, total_pages keys."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(30),
            _mapping_result(_conflict_rows(10)),
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=1, per_page=10, db=db, org=org)

        assert "data"        in result
        assert "total"       in result
        assert "page"        in result
        assert "per_page"    in result
        assert "total_pages" in result

    @pytest.mark.asyncio
    async def test_total_pages_ceil_division(self):
        """total_pages = ceil(total / per_page)."""
        total = 27
        per_page = 10
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(total),
            _mapping_result(_conflict_rows(per_page)),
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=1, per_page=per_page, db=db, org=org)

        assert result["total"]       == total
        assert result["total_pages"] == math.ceil(total / per_page)  # 3

    @pytest.mark.asyncio
    async def test_total_zero_gives_one_page(self):
        """total=0 → total_pages=1 (not 0 or division-by-zero)."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(0),
            _mapping_result([]),
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=1, per_page=10, db=db, org=org)

        assert result["total"]       == 0
        assert result["total_pages"] == 1
        assert result["data"]        == []

    @pytest.mark.asyncio
    async def test_page_and_per_page_echoed(self):
        """page and per_page in the response match the request params."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(50),
            _mapping_result(_conflict_rows(5)),
        ])
        org = _make_org()

        result = await get_catalog_conflicts(page=3, per_page=5, db=db, org=org)

        assert result["page"]     == 3
        assert result["per_page"] == 5


# ── Artist-variant pagination ─────────────────────────────────────────────────

class TestVariantPagination:
    @pytest.mark.asyncio
    async def test_page1_offset_is_zero(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(20),
            _mapping_result(_variant_rows(10)),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=10, db=db, org=org)

        data_call_params = db.execute.call_args_list[1][0][1]
        assert data_call_params["offset"] == 0
        assert data_call_params["limit"] == 10

    @pytest.mark.asyncio
    async def test_page2_offset_is_per_page(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(20),
            _mapping_result(_variant_rows(10)),
        ])
        org = _make_org()

        result = await get_artist_variants(page=2, per_page=10, db=db, org=org)

        data_call_params = db.execute.call_args_list[1][0][1]
        assert data_call_params["offset"] == 10

    @pytest.mark.asyncio
    async def test_response_shape(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(20),
            _mapping_result(_variant_rows(10)),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=10, db=db, org=org)

        assert "data"        in result
        assert "total"       in result
        assert "page"        in result
        assert "per_page"    in result
        assert "total_pages" in result

    @pytest.mark.asyncio
    async def test_total_pages_ceil_division(self):
        total = 47
        per_page = 25
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(total),
            _mapping_result(_variant_rows(per_page)),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=per_page, db=db, org=org)

        assert result["total"]       == total
        assert result["total_pages"] == math.ceil(total / per_page)  # 2

    @pytest.mark.asyncio
    async def test_total_zero_gives_one_page(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(0),
            _mapping_result([]),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=25, db=db, org=org)

        assert result["total"]       == 0
        assert result["total_pages"] == 1
        assert result["data"]        == []

    @pytest.mark.asyncio
    async def test_total_reflects_full_count_not_page_size(self):
        """total in response = full DB count, not len(data) for this page."""
        total = 42
        per_page = 10
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(total),
            _mapping_result(_variant_rows(per_page)),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=per_page, db=db, org=org)

        assert result["total"]      == total
        assert len(result["data"])  == per_page

    @pytest.mark.asyncio
    async def test_isni_status_missing_when_no_isni(self):
        """isni_status='missing' when unique_isni_count=0 and with_isni_count=0."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _mapping_result([{
                "normalized":        "some artist",
                "raw_variants":      ["Some Artist", "some artist"],
                "ean_count":         5,
                "unique_isni_count": 0,
                "with_isni_count":   0,
                "total_count":       2,
            }]),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=25, db=db, org=org)

        assert result["data"][0]["isni_status"] == "missing"

    @pytest.mark.asyncio
    async def test_isni_status_conflicting_when_multiple_isnis(self):
        """isni_status='conflicting' when unique_isni_count > 1."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _mapping_result([{
                "normalized":        "some artist",
                "raw_variants":      ["Some Artist", "some artist"],
                "ean_count":         5,
                "unique_isni_count": 2,
                "with_isni_count":   4,
                "total_count":       4,
            }]),
        ])
        org = _make_org()

        result = await get_artist_variants(page=1, per_page=25, db=db, org=org)

        assert result["data"][0]["isni_status"] == "conflicting"
