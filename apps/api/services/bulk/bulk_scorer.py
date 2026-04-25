"""
Bulk Registration File Scorer

Applies the SONGGATE readiness scoring formula to bulk registration scan results.

Formula (score-impacting severities only):
  score = 100 - min(criticals × 10, 60) - min(warnings × 3, 25)

Identifier-specific severities:
  ISNI_FORMAT / ISWC_FORMAT: Warning (−3 each)
  ISNI_MISSING / ISWC_MISSING: Info (no score impact — informational only)
  ISNI_INCONSISTENT: Warning (−3)
  ISNI_CONFLICTING: Critical (−10)

Grades:
  PASS  ≥ 80
  WARN  60–79
  FAIL  < 60
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.bulk.bulk_parser import ParsedRelease
from services.bulk.bulk_validator import BulkIssue
from services.bulk.bulk_enricher import BulkEnricher

_enricher = BulkEnricher()


def _identifier_coverage(releases: list[ParsedRelease], issues: list[BulkIssue]) -> dict[str, Any]:
    """
    Compute ISNI/ISWC coverage statistics across all releases.
    """
    total = len(releases)
    with_isni  = sum(1 for r in releases if r.isni)
    with_iswc  = sum(1 for r in releases if r.iswc)
    with_both  = sum(1 for r in releases if r.isni and r.iswc)
    with_neither = sum(1 for r in releases if not r.isni and not r.iswc)

    isni_format_errors = sum(
        1 for i in issues if i.rule_id == "BULK_ISNI_FORMAT"
    )
    iswc_format_errors = sum(
        1 for i in issues if i.rule_id == "BULK_ISWC_FORMAT"
    )

    isni_pct = round(with_isni / total * 100) if total else 0
    iswc_pct = round(with_iswc / total * 100) if total else 0

    return {
        "total_releases": total,
        "with_isni": with_isni,
        "with_isni_pct": isni_pct,
        "with_iswc": with_iswc,
        "with_iswc_pct": iswc_pct,
        "with_both": with_both,
        "with_neither": with_neither,
        "isni_format_errors": isni_format_errors,
        "iswc_format_errors": iswc_format_errors,
    }


def score_bulk_scan(
    releases: list[ParsedRelease],
    issues: list[BulkIssue],
) -> dict[str, Any]:
    """
    Score a bulk registration file scan.

    Args:
        releases: All parsed releases from the file.
        issues:   All validation issues from bulk_validator.validate_bulk_file().

    Returns a dict with:
      score                — float 0–100
      grade                — "PASS" | "WARN" | "FAIL"
      critical_count       — int
      warning_count        — int
      info_count           — int
      total_issues         — int
      total_releases       — int
      releases_with_issues — int
      cross_release_issues — list (formatted for API)
      per_release_issues   — list (grouped by row)
      identifier_coverage  — dict of ISNI/ISWC stats
      enrichment_status    — str from BulkEnricher stub
    """
    cross_release = [i for i in issues if i.scope == "cross_release"]
    per_release   = [i for i in issues if i.scope == "per_release"]

    critical_count = sum(1 for i in issues if i.severity == "critical")
    warning_count  = sum(1 for i in issues if i.severity == "warning")
    info_count     = sum(1 for i in issues if i.severity == "info")

    deductions = min(critical_count * 10.0, 60.0) + min(warning_count * 3.0, 25.0)
    score = round(max(0.0, 100.0 - deductions), 1)
    grade = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

    # Releases with at least one score-impacting issue
    affected_rows: set[int] = set()
    for issue in issues:
        if issue.severity in ("critical", "warning"):
            if issue.row_number is not None:
                affected_rows.add(issue.row_number)
            for row in issue.affected_rows:
                affected_rows.add(row)

    releases_with_issues = len(affected_rows)

    # ── Cross-release issues (API-serialisable) ───────────────────────────────
    cross_release_out = [
        {
            "id": i.id,
            "severity": i.severity,
            "rule_id": i.rule_id,
            "rule_name": i.rule_name,
            "message": i.message,
            "fix_hint": i.fix_hint,
            "affected_ean": i.affected_ean,
            "affected_rows": i.affected_rows,
        }
        for i in cross_release
    ]

    # ── Per-release issues grouped by row ─────────────────────────────────────
    per_row: dict[int, list[BulkIssue]] = defaultdict(list)
    for issue in per_release:
        if issue.row_number is not None:
            per_row[issue.row_number].append(issue)

    releases_by_row: dict[int, ParsedRelease] = {r.row_number: r for r in releases}

    per_release_out = []
    for row_num in sorted(per_row.keys()):
        release    = releases_by_row.get(row_num)
        row_issues = per_row[row_num]

        # Separate score-impacting issues from info (missing identifier notices)
        score_issues = [i for i in row_issues if i.severity in ("critical", "warning")]
        info_issues  = [i for i in row_issues if i.severity == "info"]

        per_release_out.append({
            "row_number": row_num,
            "ean":    release.ean    if release else "",
            "artist": release.artist if release else "",
            "title":  release.title  if release else "",
            "isni":   release.isni   if release else None,
            "iswc":   release.iswc   if release else None,
            "issues": [
                {
                    "id":        i.id,
                    "severity":  i.severity,
                    "rule_id":   i.rule_id,
                    "rule_name": i.rule_name,
                    "message":   i.message,
                    "fix_hint":  i.fix_hint,
                }
                for i in sorted(
                    score_issues + info_issues,
                    key=lambda x: (
                        0 if x.severity == "critical" else
                        1 if x.severity == "warning" else 2
                    ),
                )
            ],
        })

    # ── Identifier coverage stats ─────────────────────────────────────────────
    identifier_coverage = _identifier_coverage(releases, issues)

    # ── Enrichment suggestions (ArtistMatch + WorksMatch) ─────────────────────
    enrichment_by_row: dict[int, dict] = {}
    for release in releases:
        enrich_input = {
            "artist": release.artist,
            "title":  release.title,
            "isrc":   getattr(release, "isrc", "") or "",
        }
        enriched = _enricher.enrich_release(enrich_input)
        enrichment_by_row[release.row_number] = enriched

    enrichment_mock = _enricher.mock
    enrichment_status = "enriched_mock" if enrichment_mock else "enriched"

    # Attach enrichment suggestions to per-release entries
    for entry in per_release_out:
        row_num = entry["row_number"]
        enriched = enrichment_by_row.get(row_num, {})
        entry["enrichment"] = {
            "suggested_isni":     enriched.get("suggested_isni"),
            "isni_confidence":    enriched.get("isni_confidence", 0.0),
            "isni_source":        enriched.get("isni_source", "not_found"),
            "isni_match_quality": enriched.get("isni_match_quality", "none"),
            "suggested_iswc":     enriched.get("suggested_iswc"),
            "iswc_confidence":    enriched.get("iswc_confidence", 0.0),
            "iswc_source":        enriched.get("iswc_source", "not_found"),
            "iswc_match_quality": enriched.get("iswc_match_quality", "none"),
            "mock":               enriched.get("enrichment_mock", True),
        }

    return {
        "score": score,
        "grade": grade,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "total_issues": critical_count + warning_count + info_count,
        "total_releases": len(releases),
        "releases_with_issues": releases_with_issues,
        "cross_release_issues": cross_release_out,
        "per_release_issues": per_release_out,
        "identifier_coverage": identifier_coverage,
        "enrichment_status": enrichment_status,
    }
