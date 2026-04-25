# QUANSIC / LUMINATE DATA ENRICHMENT INTEGRATION
#
# This module wraps the QuansicClient to enrich bulk registration releases
# with ISNI (ArtistMatch) and ISWC (WorksMatch) suggestions.
#
# When QUANSIC_API_KEY is not set, the QuansicClient runs in mock mode and
# returns realistic pre-canned responses for well-known artists and titles.
#
# API documentation: quansic.com/api
# Contact: Luminate Music sales for API key

from __future__ import annotations

from typing import Any

from services.integrations.quansic.client import QuansicClient


class BulkEnricher:
    """
    Quansic / Luminate Data Enrichment integration.

    Uses QuansicClient to resolve ISNIs (ArtistMatch) and ISWCs (WorksMatch)
    for each release.  When QUANSIC_API_KEY is absent the client runs in mock
    mode — returning realistic stub responses for known artists/titles and
    "not_found" for all others.
    """

    def __init__(self, client: QuansicClient | None = None) -> None:
        self._client = client or QuansicClient()

    def enrich_release(self, release: dict[str, Any]) -> dict[str, Any]:
        """
        Enrich a single release dict with ISNI and ISWC suggestions.

        Expected keys on `release`: artist, title, isrc (optional).
        Returns a new dict with additional enrichment keys.
        """
        artist = release.get("artist", "")
        title  = release.get("title", "")
        isrc   = release.get("isrc", "") or ""

        # ArtistMatch — ISNI resolution
        artist_result = self._client.artist_match(artist) if artist else None
        suggested_isni        = artist_result.isni        if artist_result else None
        isni_confidence       = artist_result.confidence  if artist_result else 0.0
        isni_source           = artist_result.source      if artist_result else "not_found"
        isni_match_quality    = artist_result.match_quality if artist_result else "none"

        # WorksMatch — ISWC resolution (uses ISRC if available, otherwise title only)
        works_result = self._client.works_match(isrc, title) if title else None
        suggested_iswc        = works_result.iswc         if works_result else None
        iswc_confidence       = works_result.confidence   if works_result else 0.0
        iswc_source           = works_result.source       if works_result else "not_found"
        iswc_match_quality    = works_result.match_quality if works_result else "none"

        # Determine overall enrichment status
        mock = self._client.mock
        if suggested_isni or suggested_iswc:
            enrichment_status = "enriched_mock" if mock else "enriched"
        else:
            enrichment_status = "not_found"

        return {
            **release,
            "enrichment_status": enrichment_status,
            "suggested_isni":    suggested_isni,
            "isni_confidence":   round(isni_confidence, 3),
            "isni_source":       isni_source,
            "isni_match_quality": isni_match_quality,
            "suggested_iswc":    suggested_iswc,
            "iswc_confidence":   round(iswc_confidence, 3),
            "iswc_source":       iswc_source,
            "iswc_match_quality": iswc_match_quality,
            "enrichment_mock":   mock,
            "enrichment_note": (
                "Mock enrichment — set QUANSIC_API_KEY for live Luminate Data Enrichment"
                if mock else
                "Enriched via Luminate ArtistMatch and WorksMatch"
            ),
        }

    def enrich_batch(self, releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Enrich a batch of releases."""
        return [self.enrich_release(r) for r in releases]
