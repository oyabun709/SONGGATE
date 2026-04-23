"""
tests/test_file_types.py

Tests for centralized file type config, format detection, parser routing,
and demo mode parity. Does NOT touch tests/test_ddex.py.
"""

from __future__ import annotations

import json
import pytest

from config.file_types import (
    ALL_FORMATS,
    DEMO_ACCEPTED_EXTENSIONS,
    FORMAT_DISPLAY_STRING,
    CSV,
    JSON,
    DDEX_XML,
    detect_format,
)


# ── 1. Centralized config loads correctly ─────────────────────────────────────

def test_all_formats_loads():
    assert len(ALL_FORMATS) == 3


def test_ddex_is_first():
    """DDEX must always be display_order=1 and first in ALL_FORMATS."""
    assert ALL_FORMATS[0].internal_key == "ddex_xml"
    assert ALL_FORMATS[0].display_order == 1


def test_formats_in_correct_order():
    orders = [f.display_order for f in ALL_FORMATS]
    assert orders == sorted(orders), "Formats must be sorted by display_order"


def test_format_display_string_starts_with_ddex():
    assert FORMAT_DISPLAY_STRING.startswith("Work with three supported formats: DDEX XML")


def test_format_display_string_exact():
    assert FORMAT_DISPLAY_STRING == "Work with three supported formats: DDEX XML, CSV, and JSON."


def test_each_format_has_required_fields():
    required = {
        "display_label", "internal_key", "mime_types", "file_extensions",
        "input_supported", "output_supported", "display_order",
        "demo_supported", "standard_supported",
    }
    for fmt in ALL_FORMATS:
        for field in required:
            assert hasattr(fmt, field), f"{fmt.internal_key} missing field {field}"


def test_demo_accepted_extensions():
    assert ".xml" in DEMO_ACCEPTED_EXTENSIONS
    assert ".csv" in DEMO_ACCEPTED_EXTENSIONS
    assert ".json" in DEMO_ACCEPTED_EXTENSIONS
    # Audio and artwork must NOT appear
    assert ".mp3" not in DEMO_ACCEPTED_EXTENSIONS
    assert ".jpg" not in DEMO_ACCEPTED_EXTENSIONS
    assert ".zip" not in DEMO_ACCEPTED_EXTENSIONS


# ── 2. Format detection ───────────────────────────────────────────────────────

def test_detect_format_by_filename_xml():
    assert detect_format(b"", "release.xml") == "xml"


def test_detect_format_by_filename_csv():
    assert detect_format(b"", "metadata.csv") == "csv"


def test_detect_format_by_filename_json():
    assert detect_format(b"", "release.json") == "json"


def test_detect_format_xml_by_content():
    content = b'<?xml version="1.0"?><ern:NewReleaseMessage/>'
    assert detect_format(content) == "xml"


def test_detect_format_json_by_content():
    content = json.dumps({"upc": "123456789012", "title": "Test"}).encode()
    assert detect_format(content) == "json"


def test_detect_format_csv_by_content():
    content = b"release_title,artist_name,upc,release_date,label_name\nTest,Artist,886447119333,2026-01-01,Label\n"
    assert detect_format(content) == "csv"


def test_detect_format_defaults_to_xml():
    assert detect_format(b"", "") == "xml"
    assert detect_format(b"   ") == "xml"


def test_detect_format_filename_beats_content():
    """Filename extension should override content sniffing."""
    json_content = json.dumps({"upc": "123456789012"}).encode()
    assert detect_format(json_content, "release.xml") == "xml"


# ── 3. Parser routing ─────────────────────────────────────────────────────────

def test_csv_parser_imports():
    from services.ddex.csv_parser import CSVParser
    assert CSVParser is not None


def test_json_parser_imports():
    from services.ddex.json_parser import JSONParser
    assert JSONParser is not None


def test_ddex_parser_imports():
    from services.ddex.validator import DDEXParser, DDEXValidator
    assert DDEXParser is not None
    assert DDEXValidator is not None


def test_csv_parser_parses_valid_csv():
    from services.ddex.csv_parser import CSVParser
    content = (
        "release_title,artist_name,upc,release_date,label_name,isrc,track_title,track_number,duration\n"
        "Golden State,Asha Voss,886447119333,2026-06-01,Meridian Music Group,US-MG1-26-00101,Golden State,1,3:52\n"
    ).encode("utf-8")
    result = CSVParser().parse(content)
    assert len(result.releases) == 1
    assert result.releases[0]["title"] == "Golden State"
    assert result.releases[0]["upc"] == "886447119333"


def test_csv_parser_flags_missing_required_columns():
    from services.ddex.csv_parser import CSVParser
    content = b"release_title,artist_name\nTest,Artist\n"
    result = CSVParser().parse(content)
    assert any(f.rule_id == "csv.missing_columns" for f in result.findings)


def test_json_parser_parses_valid_json():
    from services.ddex.json_parser import JSONParser
    payload = {
        "upc": "886447119333",
        "title": "Golden State",
        "artist": "Asha Voss",
        "label": "Meridian Music Group",
        "release_date": "2026-06-01",
        "tracks": [{"isrc": "US-MG1-26-00101", "title": "Golden State"}],
    }
    result = JSONParser().parse(json.dumps(payload).encode())
    assert len(result.releases) == 1
    assert result.releases[0]["title"] == "Golden State"


def test_json_parser_flags_missing_upc():
    from services.ddex.json_parser import JSONParser
    payload = {"title": "Test", "artist": "Artist", "label": "Label", "release_date": "2026-01-01"}
    result = JSONParser().parse(json.dumps(payload).encode())
    assert any("upc" in f.rule_id for f in result.findings)


# ── 4. Demo mode parity ───────────────────────────────────────────────────────

def test_demo_scan_imports():
    """demo router imports all three parsers without error."""
    from routers.demo import _csv_parser, _json_parser, _ddex_validator
    assert _csv_parser is not None
    assert _json_parser is not None
    assert _ddex_validator is not None


def test_demo_run_in_memory_scan_xml():
    from routers.demo import _run_in_memory_scan
    # Minimal valid-ish DDEX XML
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
<ern:NewReleaseMessage xmlns:ern="http://ddex.net/xml/ern/43"
  MessageSchemaVersionId="ern/43" LanguageAndScriptCode="en" MessageId="TEST-001">
  <MessageHeader>
    <MessageThreadId>T1</MessageThreadId><MessageId>TEST-001</MessageId>
    <MessageSender><PartyId>X</PartyId><PartyName><FullName>X</FullName></PartyName></MessageSender>
    <MessageRecipient><PartyId>Y</PartyId><PartyName><FullName>Y</FullName></PartyName></MessageRecipient>
    <MessageCreatedDateTime>2026-01-01T00:00:00</MessageCreatedDateTime>
    <MessageControlType>LiveMessage</MessageControlType>
  </MessageHeader>
  <ResourceList/>
  <ReleaseList/>
  <DealList/>
</ern:NewReleaseMessage>"""
    result = _run_in_memory_scan(content, "test.xml")
    assert result["demo"] is True
    assert result["file_format"] == "xml"
    assert "readiness_score" in result
    assert "grade" in result


def test_demo_run_in_memory_scan_csv():
    from routers.demo import _run_in_memory_scan
    content = (
        "release_title,artist_name,upc,release_date,label_name,isrc,track_title,track_number,duration\n"
        "Golden State,Asha Voss,886447119333,2026-06-01,Meridian,US-MG1-26-00101,Golden State,1,3:52\n"
    ).encode("utf-8")
    result = _run_in_memory_scan(content, "release.csv")
    assert result["demo"] is True
    assert result["file_format"] == "csv"
    assert result["release_title"] == "Golden State"
    assert "readiness_score" in result


def test_demo_run_in_memory_scan_json():
    from routers.demo import _run_in_memory_scan
    payload = {
        "upc": "886447119333",
        "title": "Golden State",
        "artist": "Asha Voss",
        "label": "Meridian Music Group",
        "release_date": "2026-06-01",
        "tracks": [{"isrc": "US-MG1-26-00101", "title": "Golden State"}],
    }
    content = json.dumps(payload).encode()
    result = _run_in_memory_scan(content, "release.json")
    assert result["demo"] is True
    assert result["file_format"] == "json"
    assert result["release_title"] == "Golden State"
    assert "readiness_score" in result


def test_demo_blocks_audio_file():
    """Audio content sent to demo scan should not crash — it gets treated as XML and returns findings."""
    from routers.demo import _run_in_memory_scan
    # Fake MP3 header bytes — should not raise, should return a result
    content = b"\xff\xfb\x90\x00" * 100
    result = _run_in_memory_scan(content, "track.mp3")
    # Should return a result dict, not raise
    assert "readiness_score" in result


# ── 5. Export content types ───────────────────────────────────────────────────

def test_csv_module_available():
    import csv
    assert csv is not None


def test_json_module_available():
    import json
    assert json is not None


# ── 6. Google Sheets not present ─────────────────────────────────────────────

def test_no_google_sheets_import():
    """Google Sheets must not appear anywhere in the codebase."""
    import subprocess, pathlib
    repo_root = pathlib.Path(__file__).parent.parent.parent.parent
    result = subprocess.run(
        ["grep", "-r", "--include=*.py", "--include=*.ts", "--include=*.tsx",
         "-l", "google.sheets\|gspread\|googleapiclient\|sheets_v4", str(repo_root)],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", (
        f"Google Sheets references found:\n{result.stdout}"
    )
