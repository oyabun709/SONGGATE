"""
Tests for the DDEX validation and parsing services.

Coverage:
  DDEXValidator.validate()
    - Valid ERN 4.3 document          → 0 findings
    - Valid ERN 4.2 document          → 0 findings
    - Valid ERN 3.8.2 document        → 0 findings
    - Missing required elements       → critical findings
    - Malformed XML                   → critical well-formedness finding
    - Invalid ISRC                    → error finding
    - Invalid UPC                     → error finding
    - Wrong namespace for version     → error finding
    - Missing MessageHeader fields    → error findings

  DDEXParser.extract_metadata()
    - Extracts title, artist, UPC, ISRC, tracks, deals

  CSVParser.parse()
    - Valid CSV → 2 releases, 0 errors
    - Missing required column → critical finding
    - Invalid ISRC → error finding
    - Invalid UPC → error finding
    - Bad date format → error finding
    - BOM-encoded UTF-8 accepted

  JSONParser.parse()
    - Valid JSON array → 2 releases, 0 errors
    - Valid JSON single object → 1 release, 0 errors
    - Missing required field → error finding
    - Invalid ISRC → error finding
    - Invalid UPC → error finding
    - Malformed JSON → critical finding
"""

import json
import textwrap
from pathlib import Path

import pytest

from services.ddex.validator import DDEXFinding, DDEXParser, DDEXValidator
from services.ddex.csv_parser import CSVParser
from services.ddex.json_parser import JSONParser

# ---------------------------------------------------------------------------
# Sample XML fixtures
# ---------------------------------------------------------------------------

def _ern43(
    *,
    upc: str = "123456789012",
    isrc: str = "GB-ABC-24-00001",
    extra_header: str = "",
    omit: list[str] | None = None,
    wrong_ns: bool = False,
) -> bytes:
    ns = (
        "http://ddex.net/xml/ern/43"
        if not wrong_ns
        else "http://ddex.net/xml/ern/WRONG"
    )
    omit = omit or []
    parts = {
        "MessageHeader": f"""
        <MessageHeader>
            <MessageThreadId>THREAD-001</MessageThreadId>
            <MessageId>MSG-001</MessageId>
            <MessageSender>
                <PartyId>PADPIDA2019071701X</PartyId>
                <PartyName><FullName>Test Distributor</FullName></PartyName>
            </MessageSender>
            <MessageRecipient>
                <PartyId>PADPIDA2019071702X</PartyId>
                <PartyName><FullName>Test DSP</FullName></PartyName>
            </MessageRecipient>
            <MessageCreatedDateTime>2024-06-01T12:00:00</MessageCreatedDateTime>
            {extra_header}
        </MessageHeader>""",
        "ResourceList": f"""
        <ResourceList>
            <SoundRecording>
                <SoundRecordingType>MusicalWorkSoundRecording</SoundRecordingType>
                <SoundRecordingId>
                    <ISRC>{isrc}</ISRC>
                </SoundRecordingId>
                <ResourceReference>A1</ResourceReference>
                <ReferenceTitle><TitleText>Test Track</TitleText></ReferenceTitle>
                <Duration>PT3M45S</Duration>
                <SoundRecordingDetailsByTerritory>
                    <TerritoryCode>Worldwide</TerritoryCode>
                    <DisplayArtist>
                        <PartyName><FullName>Test Artist</FullName></PartyName>
                        <ArtistRole>MainArtist</ArtistRole>
                    </DisplayArtist>
                </SoundRecordingDetailsByTerritory>
            </SoundRecording>
        </ResourceList>""",
        "ReleaseList": f"""
        <ReleaseList>
            <Release>
                <ReleaseId>
                    <ICPN>{upc}</ICPN>
                </ReleaseId>
                <ReleaseReference>R0</ReleaseReference>
                <ReferenceTitle><TitleText>Test Album</TitleText></ReferenceTitle>
                <ReleaseResourceReferenceList>
                    <ReleaseResourceReference>A1</ReleaseResourceReference>
                </ReleaseResourceReferenceList>
                <ReleaseType>Album</ReleaseType>
                <LabelName>Test Label</LabelName>
                <IsMainRelease>true</IsMainRelease>
            </Release>
        </ReleaseList>""",
        "DealList": """
        <DealList>
            <ReleaseDeal>
                <DealReleaseReference>R0</DealReleaseReference>
                <Deal>
                    <DealTerms>
                        <CommercialModelType>PayAsYouGoModel</CommercialModelType>
                        <Usage>
                            <UseType>OnDemandStream</UseType>
                        </Usage>
                        <TerritoryCode>Worldwide</TerritoryCode>
                        <ValidityPeriod>
                            <StartDate>2024-06-01</StartDate>
                        </ValidityPeriod>
                    </DealTerms>
                </Deal>
            </ReleaseDeal>
        </DealList>""",
    }
    body = "".join(v for k, v in parts.items() if k not in omit)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NewReleaseMessage xmlns="{ns}"
    MessageSchemaVersionId="ern/43">
{body}
</NewReleaseMessage>""".encode()


def _ern_ns(version: str) -> str:
    m = {"42": "http://ddex.net/xml/ern/42", "382": "http://ddex.net/xml/ern/382"}
    return m.get(version, "http://ddex.net/xml/ern/43")


def _ern42(*, upc: str = "123456789012", isrc: str = "GB-ABC-24-00001") -> bytes:
    ns = _ern_ns("42")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NewReleaseMessage xmlns="{ns}" MessageSchemaVersionId="ern/42">
  <MessageHeader>
    <MessageId>MSG-42</MessageId>
    <MessageSender><PartyId>SENDER</PartyId></MessageSender>
    <MessageRecipient><PartyId>RECV</PartyId></MessageRecipient>
    <MessageCreatedDateTime>2024-06-01T00:00:00</MessageCreatedDateTime>
  </MessageHeader>
  <ResourceList>
    <SoundRecording>
      <SoundRecordingId><ISRC>{isrc}</ISRC></SoundRecordingId>
      <ResourceReference>A1</ResourceReference>
      <ReferenceTitle><TitleText>Track 42</TitleText></ReferenceTitle>
      <Duration>PT4M00S</Duration>
    </SoundRecording>
  </ResourceList>
  <ReleaseList>
    <Release>
      <ReleaseId><ICPN>{upc}</ICPN></ReleaseId>
      <ReleaseReference>R0</ReleaseReference>
      <ReferenceTitle><TitleText>Album 42</TitleText></ReferenceTitle>
      <ReleaseType>Album</ReleaseType>
      <IsMainRelease>true</IsMainRelease>
    </Release>
  </ReleaseList>
  <DealList>
    <ReleaseDeal>
      <DealReleaseReference>R0</DealReleaseReference>
      <Deal><DealTerms><CommercialModelType>PayAsYouGoModel</CommercialModelType></DealTerms></Deal>
    </ReleaseDeal>
  </DealList>
</NewReleaseMessage>""".encode()


def _ern382(*, upc: str = "123456789012", isrc: str = "GB-ABC-24-00001") -> bytes:
    ns = _ern_ns("382")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NewReleaseMessage xmlns="{ns}" MessageSchemaVersionId="ern/382">
  <MessageHeader>
    <MessageId>MSG-382</MessageId>
    <MessageSender><PartyId>SENDER</PartyId></MessageSender>
    <MessageRecipient><PartyId>RECV</PartyId></MessageRecipient>
    <MessageCreatedDateTime>2024-06-01T00:00:00</MessageCreatedDateTime>
  </MessageHeader>
  <ResourceList>
    <SoundRecording>
      <SoundRecordingId><ISRC>{isrc}</ISRC></SoundRecordingId>
      <ResourceReference>A1</ResourceReference>
      <ReferenceTitle><TitleText>Track 382</TitleText></ReferenceTitle>
      <Duration>PT3M30S</Duration>
    </SoundRecording>
  </ResourceList>
  <ReleaseList>
    <Release>
      <ReleaseId><ICPN>{upc}</ICPN></ReleaseId>
      <ReleaseReference>R0</ReleaseReference>
      <ReferenceTitle><TitleText>Album 382</TitleText></ReferenceTitle>
      <ReleaseType>Album</ReleaseType>
      <IsMainRelease>true</IsMainRelease>
    </Release>
  </ReleaseList>
  <DealList>
    <ReleaseDeal>
      <DealReleaseReference>R0</DealReleaseReference>
      <Deal><DealTerms><CommercialModelType>PayAsYouGoModel</CommercialModelType></DealTerms></Deal>
    </ReleaseDeal>
  </DealList>
</NewReleaseMessage>""".encode()


# ---------------------------------------------------------------------------
# DDEXValidator tests
# ---------------------------------------------------------------------------

class TestDDEXValidatorERN43:
    def test_valid_ern43_no_findings(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(), version="ERN43")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == [], f"Unexpected errors: {errors}"

    def test_valid_ern43_alias_4_3(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(), version="4.3")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == []

    def test_missing_deal_list(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(omit=["DealList"]), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.structure.missing_deallist" in rule_ids

    def test_missing_resource_list(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(omit=["ResourceList"]), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.structure.missing_resourcelist" in rule_ids

    def test_missing_release_list(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(omit=["ReleaseList"]), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.structure.missing_releaselist" in rule_ids

    def test_missing_message_header(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(omit=["MessageHeader"]), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.structure.missing_messageheader" in rule_ids

    def test_invalid_isrc(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(isrc="BADISRC"), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.metadata.isrc_format" in rule_ids

    def test_invalid_upc(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(upc="ABC123"), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.metadata.upc_format" in rule_ids

    def test_wrong_namespace(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(wrong_ns=True), version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.xml.namespace_mismatch" in rule_ids

    def test_malformed_xml(self):
        v = DDEXValidator()
        findings = v.validate(b"<unclosed>", version="ERN43")
        assert findings[0].rule_id == "ddex.xml.wellformed"
        assert findings[0].severity == "critical"

    def test_missing_message_id_in_header(self):
        v = DDEXValidator()
        # Produce XML with MessageHeader but MessageId removed
        xml = _ern43().decode().replace("<MessageId>MSG-001</MessageId>", "").encode()
        findings = v.validate(xml, version="ERN43")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.header.missing_messageid" in rule_ids

    def test_findings_have_required_fields(self):
        v = DDEXValidator()
        findings = v.validate(_ern43(isrc="BADISRC"), version="ERN43")
        for f in findings:
            assert isinstance(f, DDEXFinding)
            assert f.rule_id
            assert f.severity in ("critical", "error", "warning", "info")
            assert f.message


class TestDDEXValidatorVersions:
    def test_valid_ern42(self):
        v = DDEXValidator()
        findings = v.validate(_ern42(), version="ERN42")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == []

    def test_valid_ern42_alias_4_2(self):
        v = DDEXValidator()
        findings = v.validate(_ern42(), version="4.2")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == []

    def test_valid_ern382(self):
        v = DDEXValidator()
        findings = v.validate(_ern382(), version="ERN382")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == []

    def test_valid_ern382_alias(self):
        v = DDEXValidator()
        findings = v.validate(_ern382(), version="3.8.2")
        errors = [f for f in findings if f.severity in ("critical", "error")]
        assert errors == []

    def test_ern43_content_against_ern42_version_detects_mismatch(self):
        """Passing ERN 4.3 XML but claiming it's ERN 4.2 → namespace mismatch."""
        v = DDEXValidator()
        findings = v.validate(_ern43(), version="ERN42")
        rule_ids = [f.rule_id for f in findings]
        assert "ddex.xml.namespace_mismatch" in rule_ids


# ---------------------------------------------------------------------------
# DDEXParser tests
# ---------------------------------------------------------------------------

class TestDDEXParser:
    def test_extract_basic_fields(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern43())
        assert meta["title"] == "Test Album"
        assert meta["version"] == "ERN43"
        assert meta.get("release_type") == "Album"

    def test_extract_upc(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern43(upc="123456789012"))
        assert meta.get("upc") == "123456789012"

    def test_extract_tracks(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern43(isrc="GB-ABC-24-00001"))
        tracks = meta.get("tracks", [])
        assert len(tracks) == 1
        assert tracks[0]["isrc"] == "GB-ABC-24-00001"
        assert tracks[0]["title"] == "Test Track"
        assert tracks[0]["duration_ms"] == 225000  # PT3M45S

    def test_extract_deals(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern43())
        deals = meta.get("deals", [])
        assert len(deals) >= 1
        assert deals[0].get("deal_terms_type") == "PayAsYouGoModel"

    def test_extract_ern42(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern42())
        assert meta["version"] == "ERN42"
        assert meta.get("title") == "Album 42"

    def test_extract_ern382(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(_ern382())
        assert meta["version"] == "ERN382"

    def test_malformed_xml_returns_error(self):
        parser = DDEXParser()
        meta = parser.extract_metadata(b"NOT XML AT ALL")
        assert "_error" in meta

    def test_iso8601_duration_conversion(self):
        """PT3M45S → 225 000 ms; PT1H2M3S → 3 723 000 ms"""
        from services.ddex.validator import _iso8601_to_ms
        assert _iso8601_to_ms("PT3M45S") == 225_000
        assert _iso8601_to_ms("PT1H2M3S") == 3_723_000
        assert _iso8601_to_ms("PT30S") == 30_000
        assert _iso8601_to_ms("INVALID") is None


# ---------------------------------------------------------------------------
# CSVParser tests
# ---------------------------------------------------------------------------

VALID_CSV = textwrap.dedent("""\
    release_title,artist_name,upc,release_date,label_name,isrc,track_title,track_number,duration
    Album One,Test Artist,123456789012,2024-06-01,Test Label,GB-ABC-24-00001,Track One,1,3:45
    Album One,Test Artist,123456789012,2024-06-01,Test Label,GB-ABC-24-00002,Track Two,2,4:12
    Single One,Test Artist,123456789013,2024-07-01,Test Label,GB-ABC-24-00003,The Single,1,3:30
""").encode()


class TestCSVParser:
    def test_valid_csv_two_releases(self):
        p = CSVParser()
        result = p.parse(VALID_CSV)
        assert result.valid
        assert len(result.releases) == 2

    def test_release_tracks_grouped_by_upc(self):
        p = CSVParser()
        result = p.parse(VALID_CSV)
        album = next(r for r in result.releases if r["upc"] == "123456789012")
        assert len(album["tracks"]) == 2

    def test_single_track_count(self):
        p = CSVParser()
        result = p.parse(VALID_CSV)
        single = next(r for r in result.releases if r["upc"] == "123456789013")
        assert len(single["tracks"]) == 1

    def test_missing_required_column_critical(self):
        csv_no_upc = b"release_title,artist_name,release_date,label_name,isrc,track_title,track_number,duration\nAlbum,,2024-01-01,Label,GB-ABC-24-00001,T1,1,3:00\n"
        p = CSVParser()
        result = p.parse(csv_no_upc)
        assert not result.valid
        assert any(f.rule_id == "csv.missing_columns" for f in result.findings)

    def test_invalid_isrc_error(self):
        csv = VALID_CSV.decode().replace("GB-ABC-24-00001", "BADISRC").encode()
        p = CSVParser()
        result = p.parse(csv)
        assert any(f.rule_id == "csv.isrc_format" for f in result.findings)

    def test_invalid_upc_error(self):
        csv = VALID_CSV.decode().replace("123456789012", "NOTAUPC").encode()
        p = CSVParser()
        result = p.parse(csv)
        assert any(f.rule_id == "csv.upc_format" for f in result.findings)

    def test_bad_date_format(self):
        csv = VALID_CSV.decode().replace("2024-06-01", "06/01/2024").encode()
        p = CSVParser()
        result = p.parse(csv)
        assert any(f.rule_id == "csv.date_format" for f in result.findings)

    def test_bom_utf8_accepted(self):
        bom_csv = b"\xef\xbb\xbf" + VALID_CSV
        p = CSVParser()
        result = p.parse(bom_csv)
        assert result.valid

    def test_empty_file(self):
        p = CSVParser()
        result = p.parse(b"")
        assert not result.valid

    def test_duration_ms_conversion(self):
        p = CSVParser()
        result = p.parse(VALID_CSV)
        album = next(r for r in result.releases if r["upc"] == "123456789012")
        t1 = album["tracks"][0]
        assert t1["duration_ms"] == (3 * 60 + 45) * 1000  # 225000


# ---------------------------------------------------------------------------
# JSONParser tests
# ---------------------------------------------------------------------------

VALID_JSON_ARRAY = json.dumps([
    {
        "upc": "123456789012",
        "title": "JSON Album",
        "artist": "JSON Artist",
        "label": "JSON Label",
        "release_date": "2024-06-01",
        "tracks": [
            {"isrc": "GB-ABC-24-00001", "title": "Track One", "track_number": 1, "duration_ms": 225000},
            {"isrc": "GB-ABC-24-00002", "title": "Track Two", "track_number": 2, "duration_ms": 252000},
        ],
    },
    {
        "upc": "123456789013",
        "title": "JSON Single",
        "artist": "JSON Artist",
        "label": "JSON Label",
        "release_date": "2024-07-15",
        "tracks": [
            {"isrc": "GB-ABC-24-00003", "title": "The Single", "track_number": 1, "duration_ms": 210000},
        ],
    },
]).encode()

VALID_JSON_OBJECT = json.dumps({
    "upc": "123456789014",
    "title": "Solo JSON Release",
    "artist": "Solo Artist",
    "label": "Solo Label",
    "release_date": "2024-08-01",
    "tracks": [
        {"isrc": "GB-ABC-24-00004", "title": "Solo Track", "track_number": 1, "duration_ms": 180000},
    ],
}).encode()


class TestJSONParser:
    def test_valid_array_two_releases(self):
        p = JSONParser()
        result = p.parse(VALID_JSON_ARRAY)
        assert result.valid
        assert len(result.releases) == 2

    def test_valid_single_object(self):
        p = JSONParser()
        result = p.parse(VALID_JSON_OBJECT)
        assert result.valid
        assert len(result.releases) == 1
        assert result.releases[0]["title"] == "Solo JSON Release"

    def test_track_count(self):
        p = JSONParser()
        result = p.parse(VALID_JSON_ARRAY)
        album = next(r for r in result.releases if r["upc"] == "123456789012")
        assert len(album["tracks"]) == 2

    def test_missing_required_field(self):
        bad = json.dumps([{"upc": "123456789012", "title": "No Artist", "label": "L", "release_date": "2024-01-01", "tracks": []}]).encode()
        p = JSONParser()
        result = p.parse(bad)
        assert any("artist" in f.rule_id for f in result.findings)

    def test_invalid_upc(self):
        bad = json.dumps([{"upc": "NOTAUPC", "title": "T", "artist": "A", "label": "L", "release_date": "2024-01-01", "tracks": [{"isrc": "GB-ABC-24-00001", "title": "T1"}]}]).encode()
        p = JSONParser()
        result = p.parse(bad)
        assert any(f.rule_id == "json.upc_format" for f in result.findings)

    def test_invalid_isrc_in_track(self):
        bad = json.dumps([{"upc": "123456789012", "title": "T", "artist": "A", "label": "L", "release_date": "2024-01-01", "tracks": [{"isrc": "BADISRC", "title": "T1"}]}]).encode()
        p = JSONParser()
        result = p.parse(bad)
        assert any(f.rule_id == "json.track.isrc_format" for f in result.findings)

    def test_malformed_json(self):
        p = JSONParser()
        result = p.parse(b"{not valid json")
        assert not result.valid
        assert result.findings[0].rule_id == "json.parse"

    def test_missing_tracks_array(self):
        bad = json.dumps([{"upc": "123456789012", "title": "T", "artist": "A", "label": "L", "release_date": "2024-01-01"}]).encode()
        p = JSONParser()
        result = p.parse(bad)
        assert any(f.rule_id == "json.no_tracks" for f in result.findings)

    def test_bad_date_format(self):
        bad = json.dumps([{"upc": "123456789012", "title": "T", "artist": "A", "label": "L", "release_date": "06/01/2024", "tracks": [{"isrc": "GB-ABC-24-00001", "title": "T1"}]}]).encode()
        p = JSONParser()
        result = p.parse(bad)
        assert any(f.rule_id == "json.date_format" for f in result.findings)

    def test_deals_parsed(self):
        payload = json.dumps([{
            "upc": "123456789012",
            "title": "T", "artist": "A", "label": "L", "release_date": "2024-01-01",
            "deals": [{"territory": "Worldwide", "commercial_model": "PayAsYouGoModel"}],
            "tracks": [{"isrc": "GB-ABC-24-00001", "title": "T1"}],
        }]).encode()
        p = JSONParser()
        result = p.parse(payload)
        assert result.valid
        assert result.releases[0]["deals"][0]["territory"] == "Worldwide"
