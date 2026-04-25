"""
Tests for Bulk Registration File support.

Coverage:
  BulkParser
    - Valid pipe-delimited file → correct release count
    - Valid CSV file → correct release count
    - Header row is skipped
    - Empty rows are skipped
    - Missing delimiter columns handled gracefully

  EAN validation
    - Valid EAN-13 passes
    - Too short EAN fails
    - Too long EAN fails
    - Non-digit characters fail
    - Bad check digit fails
    - All-zeros EAN fails

  Date validation
    - Valid MMDDYY parses correctly
    - Invalid month (13) fails as critical
    - Invalid day for month (Feb 30) fails as critical
    - Non-digit date string fails

  Per-release checks
    - Missing artist triggers warning
    - Missing title triggers warning
    - Missing imprint AND label triggers warning
    - Unknown NARM config code triggers warning
    - Date more than 2 years in past triggers warning

  Cross-release checks
    - Duplicate EAN detection triggers critical
    - Artist name inconsistency across duplicate EANs triggers warning
    - Title case inconsistency across duplicate EANs triggers warning
    - Future date > 6 months out triggers info

  Scorer
    - Score formula: 100 - min(C*10,60) - min(W*3,25)
    - Grade PASS at score >= 80
    - Grade WARN at score 60–79
    - Grade FAIL at score < 60

  Sample file
    - Sample file parses to 10 releases
    - Sample file produces 2 critical duplicate EAN findings
    - Sample file score is FAIL
"""

from __future__ import annotations

from datetime import date

import pytest

from services.bulk.bulk_parser import ParsedRelease, parse_bulk_file, _parse_mmddyy
from services.bulk.bulk_validator import validate_bulk_file, validate_ean
from services.bulk.bulk_scorer import score_bulk_scan


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_release(
    ean: str = "0753088935176",
    artist: str = "Bill Evans Trio",
    title: str = "Explorations",
    date_raw: str = "010626",
    imprint: str | None = "Riverside Records",
    label: str | None = "Fantasy Records",
    narm: str = "00",
    row: int = 1,
) -> ParsedRelease:
    return ParsedRelease(
        ean=ean,
        artist=artist,
        title=title,
        release_date_raw=date_raw,
        release_date_parsed=_parse_mmddyy(date_raw),
        imprint=imprint,
        label=label,
        narm_config=narm,
        row_number=row,
    )


_VALID_PIPE = b"""EAN|Artist|Title|Release Date|Imprint|Label|NARM Config
0753088935176|Bill Evans Trio|Explorations|010626|Riverside Records|Fantasy Records|00
0820233171922|YOASOBI|E-SIDE 4|042426|Sony Music|Sony Music Entertainment Japan|02
"""

_VALID_CSV = b"""EAN,Artist,Title,Release Date,Imprint,Label,NARM Config
0753088935176,Bill Evans Trio,Explorations,010626,Riverside Records,Fantasy Records,00
0820233171922,YOASOBI,E-SIDE 4,042426,Sony Music,Sony Music Entertainment Japan,02
"""

_WITH_EMPTY_ROWS = b"""EAN|Artist|Title|Release Date|Imprint|Label|NARM Config
0753088935176|Bill Evans Trio|Explorations|010626|Riverside|Fantasy|00

|||||||

0820233171922|YOASOBI|E-SIDE 4|042426|Sony|Sony|02
"""

_NO_HEADER = b"""0753088935176|Bill Evans Trio|Explorations|010626|Riverside Records|Fantasy Records|00
0820233171922|YOASOBI|E-SIDE 4|042426|Sony Music|Sony Music Entertainment Japan|02
"""


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestBulkParser:
    def test_pipe_delimited_parses_correct_count(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert len(releases) == 2

    def test_csv_parses_correct_count(self):
        releases = parse_bulk_file(_VALID_CSV)
        assert len(releases) == 2

    def test_header_row_skipped(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].ean == "0753088935176"
        assert releases[0].row_number == 1

    def test_empty_rows_skipped(self):
        releases = parse_bulk_file(_WITH_EMPTY_ROWS)
        assert len(releases) == 2

    def test_no_header_row_parses_all(self):
        releases = parse_bulk_file(_NO_HEADER)
        assert len(releases) == 2

    def test_artist_parsed_correctly(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].artist == "Bill Evans Trio"

    def test_release_date_raw_preserved(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].release_date_raw == "010626"

    def test_release_date_parsed_to_date_object(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].release_date_parsed == date(2026, 1, 6)

    def test_imprint_and_label_parsed(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].imprint == "Riverside Records"
        assert releases[0].label == "Fantasy Records"

    def test_narm_config_parsed(self):
        releases = parse_bulk_file(_VALID_PIPE)
        assert releases[0].narm_config == "00"

    def test_utf8_bom_accepted(self):
        bom_content = b"\xef\xbb\xbf" + _VALID_PIPE[:]  # UTF-8 BOM
        releases = parse_bulk_file(bom_content)
        assert len(releases) == 2


# ── EAN validation tests ──────────────────────────────────────────────────────

class TestEANValidation:
    def test_valid_ean_passes(self):
        assert validate_ean("0753088935176") is None

    def test_valid_ean_second_sample(self):
        assert validate_ean("0820233171922") is None

    def test_too_short_fails(self):
        assert validate_ean("075308893517") is not None

    def test_too_long_fails(self):
        assert validate_ean("07530889351760") is not None

    def test_non_digit_characters_fail(self):
        assert validate_ean("075308893517X") is not None

    def test_empty_string_fails(self):
        assert validate_ean("") is not None

    def test_bad_check_digit_fails(self):
        # Change last digit of valid EAN
        assert validate_ean("0753088935170") is not None

    def test_all_zeros_fails(self):
        assert validate_ean("0000000000000") is not None

    def test_check_digit_algorithm_correct(self):
        # Verify the algorithm on known EANs from the sample file
        known_valid = [
            "0613365096917",
            "0711574971718",
            "0810179612641",
            "0199957600262",
            "0753088935176",
            "0820233171922",
            "0196874342671",
            "0199584421445",
        ]
        for ean in known_valid:
            assert validate_ean(ean) is None, f"Expected valid but got error for {ean}"


# ── Date parsing tests ────────────────────────────────────────────────────────

class TestDateParsing:
    def test_valid_date_april_18_2026(self):
        d = _parse_mmddyy("041826")
        assert d == date(2026, 4, 18)

    def test_valid_date_january_06_2026(self):
        d = _parse_mmddyy("010626")
        assert d == date(2026, 1, 6)

    def test_invalid_month_13(self):
        d = _parse_mmddyy("131526")
        assert d is None

    def test_invalid_day_feb_30(self):
        d = _parse_mmddyy("023026")
        assert d is None

    def test_non_digit_string(self):
        d = _parse_mmddyy("MMDDYY")
        assert d is None

    def test_too_short(self):
        d = _parse_mmddyy("0418")
        assert d is None

    def test_too_long(self):
        d = _parse_mmddyy("0418261")
        assert d is None


# ── Per-release validation ────────────────────────────────────────────────────

class TestPerReleaseValidation:
    def _validate_one(self, release: ParsedRelease, today: date = date(2026, 4, 25)):
        return validate_bulk_file([release], today=today)

    def test_clean_release_no_score_impacting_issues(self):
        # A release with all required fields should have no critical or warning issues.
        # Phase 2 adds ISNI/ISWC missing notices (info severity — no score impact).
        r = make_release()
        issues = self._validate_one(r)
        score_issues = [i for i in issues if i.severity in ("critical", "warning")]
        assert score_issues == []

    def test_invalid_ean_triggers_critical(self):
        r = make_release(ean="123")
        issues = self._validate_one(r)
        criticals = [i for i in issues if i.severity == "critical"]
        assert len(criticals) >= 1
        assert any("EAN" in i.rule_name for i in criticals)

    def test_bad_check_digit_triggers_critical(self):
        r = make_release(ean="0753088935170")  # valid length, wrong check digit
        issues = self._validate_one(r)
        assert any(i.severity == "critical" for i in issues)

    def test_missing_artist_triggers_warning(self):
        r = make_release(artist="")
        issues = self._validate_one(r)
        assert any(i.severity == "warning" and "Artist" in i.rule_name for i in issues)

    def test_missing_title_triggers_warning(self):
        r = make_release(title="")
        issues = self._validate_one(r)
        assert any(i.severity == "warning" and "Title" in i.rule_name for i in issues)

    def test_missing_imprint_and_label_triggers_warning(self):
        r = make_release(imprint=None, label=None)
        issues = self._validate_one(r)
        assert any("Imprint" in i.rule_name for i in issues)

    def test_imprint_present_no_label_no_warning(self):
        r = make_release(imprint="My Imprint", label=None)
        issues = self._validate_one(r)
        assert not any("Imprint" in i.rule_name for i in issues)

    def test_unknown_narm_code_triggers_warning(self):
        r = make_release(narm="99")
        issues = self._validate_one(r)
        assert any("NARM" in i.rule_name for i in issues)

    def test_known_narm_codes_no_warning(self):
        for code in ["00", "02", "04", "05", "06"]:
            r = make_release(narm=code)
            issues = self._validate_one(r)
            assert not any("NARM" in i.rule_name for i in issues), f"Unexpected NARM warning for code {code}"

    def test_invalid_month_triggers_critical(self):
        r = make_release(date_raw="131526")
        issues = self._validate_one(r)
        criticals = [i for i in issues if i.severity == "critical" and "Date" in i.rule_name]
        assert len(criticals) >= 1

    def test_invalid_day_triggers_critical(self):
        r = make_release(date_raw="023026")
        issues = self._validate_one(r)
        criticals = [i for i in issues if i.severity == "critical" and "Date" in i.rule_name]
        assert len(criticals) >= 1

    def test_date_over_2_years_past_triggers_warning(self):
        r = make_release(date_raw="011520")  # January 15, 2020 — > 2 years before 2026
        issues = self._validate_one(r, today=date(2026, 4, 25))
        assert any("past" in i.rule_name.lower() or "Old" in i.rule_name for i in issues)


# ── Cross-release validation ──────────────────────────────────────────────────

class TestCrossReleaseValidation:
    def test_duplicate_ean_triggers_critical(self):
        r1 = make_release(ean="0753088935176", row=1)
        r2 = make_release(ean="0753088935176", row=2)
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        cross = [i for i in issues if i.scope == "cross_release" and i.severity == "critical"]
        assert len(cross) >= 1
        assert any("0753088935176" in i.message for i in cross)

    def test_no_duplicate_ean_no_critical(self):
        r1 = make_release(ean="0753088935176", row=1)
        r2 = make_release(ean="0820233171922", row=2)
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        cross_criticals = [i for i in issues if i.scope == "cross_release" and i.severity == "critical"]
        assert len(cross_criticals) == 0

    def test_artist_inconsistency_triggers_warning(self):
        r1 = make_release(ean="0753088935176", artist="RZA & Juice Crew", row=1)
        r2 = make_release(ean="0753088935176", artist="RZA, Juice Crew", row=2)
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        artist_issues = [i for i in issues if "Artist" in i.rule_name and i.scope == "cross_release"]
        assert len(artist_issues) >= 1

    def test_title_case_inconsistency_triggers_warning(self):
        r1 = make_release(ean="0753088935176", title="A Tribute To Pharoah Sanders", row=1)
        r2 = make_release(ean="0753088935176", title="A Tribute to Pharoah Sanders", row=2)
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        title_issues = [i for i in issues if "Title" in i.rule_name and i.scope == "cross_release"]
        assert len(title_issues) >= 1

    def test_future_date_over_6_months_triggers_info(self):
        r = make_release(date_raw="012728", row=1)  # January 27, 2028 — > 6 months from 2026
        r = ParsedRelease(
            ean=r.ean,
            artist=r.artist,
            title=r.title,
            release_date_raw="012728",
            release_date_parsed=date(2028, 1, 27),
            imprint=r.imprint,
            label=r.label,
            narm_config=r.narm_config,
            row_number=1,
        )
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        info_issues = [i for i in issues if i.severity == "info"]
        assert len(info_issues) >= 1

    def test_future_date_under_6_months_no_info(self):
        # 3 months out — should not trigger a date info notice
        r = make_release(date_raw="072526", row=1)  # July 25, 2026 — ~3 months out
        r = ParsedRelease(
            ean=r.ean, artist=r.artist, title=r.title,
            release_date_raw="072526", release_date_parsed=date(2026, 7, 25),
            imprint=r.imprint, label=r.label, narm_config=r.narm_config, row_number=1,
        )
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        date_info = [i for i in issues if i.severity == "info" and "Date" in i.rule_name]
        assert len(date_info) == 0


# ── Scorer tests ──────────────────────────────────────────────────────────────

class TestBulkScorer:
    def _make_issue(self, severity: str, scope: str = "per_release"):
        from services.bulk.bulk_validator import BulkIssue
        return BulkIssue(
            id="test",
            severity=severity,
            rule_id="",
            rule_name="Test",
            message="Test",
            fix_hint="Fix it",
            scope=scope,
            row_number=1,
            affected_ean=None,
            affected_rows=[],
        )

    def test_no_issues_score_100(self):
        result = score_bulk_scan([], [])
        assert result["score"] == 100.0
        assert result["grade"] == "PASS"

    def test_one_critical_deducts_10(self):
        issues = [self._make_issue("critical")]
        result = score_bulk_scan([], issues)
        assert result["score"] == 90.0
        assert result["grade"] == "PASS"

    def test_six_criticals_cap_at_60_deduction(self):
        issues = [self._make_issue("critical") for _ in range(7)]
        result = score_bulk_scan([], issues)
        assert result["score"] == 40.0  # 100 - 60 = 40
        assert result["grade"] == "FAIL"

    def test_one_warning_deducts_3(self):
        issues = [self._make_issue("warning")]
        result = score_bulk_scan([], issues)
        assert result["score"] == 97.0

    def test_grade_pass_at_80(self):
        # 2 criticals = 20 deduction → score 80 = PASS
        issues = [self._make_issue("critical"), self._make_issue("critical")]
        result = score_bulk_scan([], issues)
        assert result["score"] == 80.0
        assert result["grade"] == "PASS"

    def test_grade_warn_at_79(self):
        # 2 criticals + 1 warning = 23 deduction → score 77 = WARN
        issues = [
            self._make_issue("critical"),
            self._make_issue("critical"),
            self._make_issue("warning"),
        ]
        result = score_bulk_scan([], issues)
        assert result["score"] == 77.0
        assert result["grade"] == "WARN"

    def test_grade_fail_below_60(self):
        # 4 criticals + 5 warnings = 40 + 15 = 55 → score 45 = FAIL
        issues = (
            [self._make_issue("critical") for _ in range(4)] +
            [self._make_issue("warning") for _ in range(5)]
        )
        result = score_bulk_scan([], issues)
        assert result["score"] == 45.0
        assert result["grade"] == "FAIL"

    def test_formula_matches_spec_2_critical_8_warning(self):
        # 2 criticals * 10 = 20, 8 warnings * 3 = 24 → 100 - 20 - 24 = 56
        issues = (
            [self._make_issue("critical") for _ in range(2)] +
            [self._make_issue("warning") for _ in range(8)]
        )
        result = score_bulk_scan([], issues)
        assert result["score"] == 56.0
        assert result["grade"] == "FAIL"

    def test_total_releases_counted(self):
        releases = [make_release(row=i) for i in range(1, 4)]
        result = score_bulk_scan(releases, [])
        assert result["total_releases"] == 3

    def test_cross_release_issues_separated(self):
        from services.bulk.bulk_validator import BulkIssue
        cross = BulkIssue(
            id="x", severity="critical", rule_id="BULK_EAN_DUPLICATE", rule_name="Dup EAN",
            message="msg", fix_hint="fix", scope="cross_release",
            row_number=None, affected_ean="123", affected_rows=[1, 2],
        )
        per = BulkIssue(
            id="y", severity="warning", rule_id="BULK_IMPRINT_MISSING", rule_name="Missing Label",
            message="msg", fix_hint="fix", scope="per_release",
            row_number=1, affected_ean=None, affected_rows=[],
        )
        releases = [make_release(row=1)]
        result = score_bulk_scan(releases, [cross, per])
        assert len(result["cross_release_issues"]) == 1
        assert len(result["per_release_issues"]) == 1


# ── Sample file end-to-end ────────────────────────────────────────────────────

class TestSampleFile:
    def _load_sample(self) -> bytes:
        from pathlib import Path
        sample_path = Path(__file__).parent.parent / "data" / "sample_bulk_registration.txt"
        return sample_path.read_bytes()

    def test_sample_parses_to_10_releases(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        assert len(releases) == 10

    def test_sample_has_2_duplicate_ean_criticals(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        dup_criticals = [
            i for i in issues
            if i.scope == "cross_release" and i.severity == "critical" and "Duplicate" in i.rule_name
        ]
        assert len(dup_criticals) == 2

    def test_sample_rza_inconsistency_detected(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        artist_issues = [i for i in issues if "Artist" in i.rule_name and i.scope == "cross_release"]
        assert len(artist_issues) >= 1
        assert any("RZA" in i.message for i in artist_issues)

    def test_sample_wendell_title_case_detected(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        title_issues = [i for i in issues if "Title" in i.rule_name and i.scope == "cross_release"]
        assert len(title_issues) >= 1

    def test_sample_missing_imprint_label_on_6_rows(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        imprint_issues = [
            i for i in issues
            if i.scope == "per_release" and "Imprint" in i.rule_name
        ]
        assert len(imprint_issues) == 6

    def test_sample_scores_as_fail(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        result = score_bulk_scan(releases, issues)
        assert result["grade"] == "FAIL"
        assert result["score"] < 60

    def test_sample_all_eans_valid(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        ean_issues = [i for i in issues if i.scope == "per_release" and "EAN" in i.rule_name]
        assert len(ean_issues) == 0  # all EANs in sample are valid format

    def test_sample_four_releases_have_isni(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        with_isni = [r for r in releases if r.isni]
        assert len(with_isni) == 4

    def test_sample_four_releases_have_iswc(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        with_iswc = [r for r in releases if r.iswc]
        assert len(with_iswc) == 4

    def test_sample_identifier_coverage_stats(self):
        content = self._load_sample()
        releases = parse_bulk_file(content)
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        result = score_bulk_scan(releases, issues)
        cov = result["identifier_coverage"]
        assert cov["total_releases"] == 10
        assert cov["with_isni"] == 4
        assert cov["with_iswc"] == 4
        assert cov["with_both"] == 4
        assert cov["with_neither"] == 6


# ── ISNI validation ───────────────────────────────────────────────────────────

class TestISNIValidation:
    def test_valid_isni_passes(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("0000000121455467") is None

    def test_valid_isni_with_hyphens_passes(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("0000-0001-2145-5467") is None

    def test_too_short_isni_fails(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("000000012145546") is not None  # 15 digits

    def test_too_long_isni_fails(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("00000001214554670") is not None  # 17 digits

    def test_non_digit_isni_fails(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("000000012145546X") is not None

    def test_all_zero_isni_fails(self):
        from services.bulk.bulk_validator import validate_isni
        assert validate_isni("0000000000000000") is not None

    def test_missing_isni_triggers_info_not_warning(self):
        r = make_release()  # no ISNI (default)
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        isni_issues = [i for i in issues if i.rule_id == "BULK_ISNI_MISSING"]
        assert len(isni_issues) == 1
        assert isni_issues[0].severity == "info"

    def test_invalid_isni_triggers_warning(self):
        from services.bulk.bulk_parser import ParsedRelease
        r = ParsedRelease(
            ean="0753088935176", artist="Bill Evans Trio", title="Explorations",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=1,
            isni="INVALID123",
        )
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        assert any(i.rule_id == "BULK_ISNI_FORMAT" and i.severity == "warning" for i in issues)

    def test_isni_inconsistency_triggers_warning(self):
        from services.bulk.bulk_parser import ParsedRelease
        r1 = ParsedRelease(
            ean="0753088935176", artist="Bill Evans Trio", title="Explorations",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=1,
            isni="0000000121455467",
        )
        r2 = ParsedRelease(
            ean="0820233171922", artist="Bill Evans Trio", title="Waltz for Debby",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=2,
            isni=None,  # same artist, no ISNI
        )
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        assert any(i.rule_id == "BULK_ISNI_INCONSISTENT" and i.severity == "warning" for i in issues)

    def test_isni_conflict_triggers_critical(self):
        from services.bulk.bulk_parser import ParsedRelease
        r1 = ParsedRelease(
            ean="0753088935176", artist="Bill Evans Trio", title="Explorations",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=1,
            isni="0000000121455467",
        )
        r2 = ParsedRelease(
            ean="0820233171922", artist="Bill Evans Trio", title="Waltz for Debby",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=2,
            isni="0000000504174930",  # different ISNI, same artist
        )
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        assert any(i.rule_id == "BULK_ISNI_CONFLICTING" and i.severity == "critical" for i in issues)


# ── ISWC validation ───────────────────────────────────────────────────────────

class TestISWCValidation:
    def test_valid_iswc_with_hyphens_passes(self):
        from services.bulk.bulk_validator import validate_iswc
        assert validate_iswc("T-070195720-5") is None

    def test_valid_iswc_without_hyphens_passes(self):
        from services.bulk.bulk_validator import validate_iswc
        assert validate_iswc("T0701957205") is None

    def test_invalid_iswc_wrong_prefix_fails(self):
        from services.bulk.bulk_validator import validate_iswc
        assert validate_iswc("W-070195720-5") is not None

    def test_invalid_iswc_too_few_digits_fails(self):
        from services.bulk.bulk_validator import validate_iswc
        assert validate_iswc("T-07019572-5") is not None  # only 8 middle digits

    def test_missing_iswc_triggers_info_not_warning(self):
        r = make_release()  # no ISWC (default)
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        iswc_issues = [i for i in issues if i.rule_id == "BULK_ISWC_MISSING"]
        assert len(iswc_issues) == 1
        assert iswc_issues[0].severity == "info"

    def test_invalid_iswc_triggers_warning(self):
        from services.bulk.bulk_parser import ParsedRelease
        r = ParsedRelease(
            ean="0753088935176", artist="Bill Evans Trio", title="Explorations",
            release_date_raw="010626", release_date_parsed=date(2026, 1, 6),
            imprint="Riverside", label="Fantasy", narm_config="00", row_number=1,
            iswc="BADFORMAT",
        )
        issues = validate_bulk_file([r], today=date(2026, 4, 25))
        assert any(i.rule_id == "BULK_ISWC_FORMAT" and i.severity == "warning" for i in issues)


# ── Identifier coverage ───────────────────────────────────────────────────────

class TestIdentifierCoverage:
    def test_zero_coverage_when_no_identifiers(self):
        releases = [make_release(row=i) for i in range(1, 4)]
        issues = validate_bulk_file(releases, today=date(2026, 4, 25))
        result = score_bulk_scan(releases, issues)
        cov = result["identifier_coverage"]
        assert cov["total_releases"] == 3
        assert cov["with_isni"] == 0
        assert cov["with_isni_pct"] == 0
        assert cov["with_iswc"] == 0
        assert cov["with_neither"] == 3

    def test_partial_coverage_stats(self):
        from services.bulk.bulk_parser import ParsedRelease
        r1 = ParsedRelease(
            ean="0753088935176", artist="A", title="T",
            release_date_raw="041826", release_date_parsed=date(2026, 4, 18),
            imprint="L", label="L", narm_config="00", row_number=1,
            isni="0000000121455467", iswc="T-070195720-5",
        )
        r2 = make_release(row=2)  # no identifiers
        issues = validate_bulk_file([r1, r2], today=date(2026, 4, 25))
        result = score_bulk_scan([r1, r2], issues)
        cov = result["identifier_coverage"]
        assert cov["total_releases"] == 2
        assert cov["with_isni"] == 1
        assert cov["with_isni_pct"] == 50
        assert cov["with_iswc"] == 1
        assert cov["with_both"] == 1
        assert cov["with_neither"] == 1

    def test_enrichment_status_is_stub(self):
        result = score_bulk_scan([], [])
        assert result["enrichment_status"] == "pending_api_integration"


# ── Enricher stub ─────────────────────────────────────────────────────────────

class TestBulkEnricher:
    def test_enrich_release_returns_stub(self):
        from services.bulk.bulk_enricher import BulkEnricher
        enricher = BulkEnricher()
        out = enricher.enrich_release({"artist": "Bill Evans", "ean": "0753088935176"})
        assert out["enrichment_status"] == "pending_api_integration"
        assert out["suggested_isni"] is None
        assert out["suggested_iswc"] is None
        assert out["artist"] == "Bill Evans"

    def test_enrich_batch_returns_all(self):
        from services.bulk.bulk_enricher import BulkEnricher
        enricher = BulkEnricher()
        releases = [{"artist": "A"}, {"artist": "B"}, {"artist": "C"}]
        out = enricher.enrich_batch(releases)
        assert len(out) == 3
        assert all(r["enrichment_status"] == "pending_api_integration" for r in out)
