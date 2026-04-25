"""
Bulk Registration File Scorer

Applies the SONGGATE readiness scoring formula to bulk registration scan results.

Formula:
  score = 100 - min(criticals × 10, 60) - min(warnings × 3, 25)

Grades:
  PASS  ≥ 80
  WARN  60–79
  FAIL  < 60

Score applies to the file as a whole. Also generates a per-release issue
summary showing which specific releases have problems.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any

from services.bulk.bulk_parser import ParsedRelease
from services.bulk.bulk_validator import BulkIssue


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
      score            — int 0–100
      grade            — "PASS" | "WARN" | "FAIL"
      critical_count   — int
      warning_count    — int
      info_count        — int
      total_issues     — int
      total_releases   — int
      releases_with_issues — int
      cross_release_issues — list of cross-release issues (formatted for API)
      per_release_issues   — list of per-release summaries grouped by row
    """
    cross_release = [i for i in issues if i.scope == "cross_release"]
    per_release   = [i for i in issues if i.scope == "per_release"]

    critical_count = sum(1 for i in issues if i.severity == "critical")
    warning_count  = sum(1 for i in issues if i.severity == "warning")
    info_count     = sum(1 for i in issues if i.severity == "info")

    deductions = min(critical_count * 10.0, 60.0) + min(warning_count * 3.0, 25.0)
    score = round(max(0.0, 100.0 - deductions), 1)
    grade = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

    # Releases with at least one issue (by row_number)
    affected_rows: set[int] = set()
    for issue in issues:
        if issue.row_number is not None:
            affected_rows.add(issue.row_number)
        # Cross-release issues also affect specific rows
        for row in issue.affected_rows:
            affected_rows.add(row)

    releases_with_issues = len(affected_rows)

    # Build cross_release_issues list (API-serialisable)
    cross_release_out = [
        {
            "id": i.id,
            "severity": i.severity,
            "rule_name": i.rule_name,
            "message": i.message,
            "fix_hint": i.fix_hint,
            "affected_ean": i.affected_ean,
            "affected_rows": i.affected_rows,
        }
        for i in cross_release
    ]

    # Group per-release issues by row_number
    per_row: dict[int, list[BulkIssue]] = defaultdict(list)
    for issue in per_release:
        if issue.row_number is not None:
            per_row[issue.row_number].append(issue)

    # Build per_release_issues list, merging with release metadata
    releases_by_row: dict[int, ParsedRelease] = {r.row_number: r for r in releases}

    per_release_out = []
    for row_num in sorted(per_row.keys()):
        release = releases_by_row.get(row_num)
        row_issues = per_row[row_num]
        per_release_out.append({
            "row_number": row_num,
            "ean": release.ean if release else "",
            "artist": release.artist if release else "",
            "title": release.title if release else "",
            "issues": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "rule_name": i.rule_name,
                    "message": i.message,
                    "fix_hint": i.fix_hint,
                }
                for i in sorted(row_issues, key=lambda x: (
                    0 if x.severity == "critical" else 1 if x.severity == "warning" else 2
                ))
            ],
        })

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
    }
