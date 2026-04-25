"""
seed_catalog_demo.py — Seed catalog_index with 45 realistic releases for the demo account.

Simulates:
  - 45 releases (43 unique EANs, 2 EAN conflict pairs)
  - 2 EAN conflicts: same EAN, different artist_normalized across two "scans"
  - 2 artist variant cases: same artist_normalized, different raw strings
  - ~40% ISNI and ISWC coverage
  - Realistic jazz/soul catalog data matching Luminate/Riverside Records context

Usage:
  python3 scripts/seed_catalog_demo.py
  python3 scripts/seed_catalog_demo.py --org-id <uuid>  # override org
  python3 scripts/seed_catalog_demo.py --clear          # clear existing demo rows first
"""

import argparse
import uuid
from datetime import date, datetime, timezone
import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────

DSN = "postgresql://neondb_owner:npg_5LmReAn1DHOT@ep-quiet-bread-am15ggdr.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require"

# Primary demo org (Smoke Test Org)
DEMO_ORG_ID = "10e77e02-66e8-4d82-a709-84d849c34359"

# ── Normalization (mirror catalog_indexer.py) ─────────────────────────────────

import re
import unicodedata

def normalize_artist(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFC", raw).lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r",\s+", " and ", s)
    s = re.sub(r"\s*\b(?:feat\.|ft\.|featuring)\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_title(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFC", raw).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

# ── Seed data ─────────────────────────────────────────────────────────────────
#
# 45 rows total:
#   - Rows 1–41: 41 distinct EANs (unique releases)
#   - Rows 42–43: EAN conflict pair A — "Bill Evans Trio" vs "The Bill Evans Trio"
#   - Rows 44–45: Artist variant pair B — "RZA & Juice Crew" vs "RZA, Juice Crew"
#     (same EAN, same normalized artist, different raw strings)
#
# ISNI assigned to 18 releases (~40%)
# ISWC assigned to 18 releases (~40%)

ISNI_POOL = [
    "0000000121455467",
    "0000000073776014",
    "0000000114026673",
    "0000000058051093",
    "0000000050980126",
    "0000000078467222",
    "0000000122501780",
    "0000000073540091",
    "0000000119003890",
    "0000000075524832",
    "0000000058012201",
    "0000000079892744",
    "0000000068254902",
    "0000000114987655",
    "0000000124210388",
    "0000000062103498",
    "0000000109032871",
    "0000000094587123",
]

ISWC_POOL = [
    "T-034.524.680-1",
    "T-010.673.493-5",
    "T-055.432.178-2",
    "T-072.891.034-8",
    "T-043.219.876-3",
    "T-088.654.321-7",
    "T-021.987.654-0",
    "T-067.432.198-4",
    "T-031.654.897-6",
    "T-092.345.678-9",
    "T-014.567.890-1",
    "T-056.789.012-3",
    "T-078.901.234-5",
    "T-023.456.789-2",
    "T-049.012.345-6",
    "T-081.234.567-8",
    "T-015.678.901-4",
    "T-037.890.123-7",
]

# 41 unique releases
_RELEASES = [
    # Bill Evans
    {"ean": "0753088935176", "artist": "Bill Evans Trio",        "title": "Explorations",               "date": date(2026, 1, 6),  "imprint": "Riverside Records",   "label": "Fantasy Records",  "narm": "00"},
    {"ean": "0753088935183", "artist": "Bill Evans Trio",        "title": "Portrait in Jazz",            "date": date(2026, 1, 6),  "imprint": "Riverside Records",   "label": "Fantasy Records",  "narm": "00"},
    {"ean": "0753088935190", "artist": "Bill Evans Trio",        "title": "Waltz for Debby",             "date": date(2026, 2, 3),  "imprint": "Riverside Records",   "label": "Fantasy Records",  "narm": "00"},
    {"ean": "0753088935206", "artist": "Bill Evans Trio",        "title": "Sunday at the Village Vanguard", "date": date(2026, 2, 3), "imprint": "Riverside Records", "label": "Fantasy Records",  "narm": "00"},
    # Miles Davis
    {"ean": "0888072307896", "artist": "Miles Davis",            "title": "Kind of Blue",                "date": date(2026, 1, 13), "imprint": "Columbia Records",    "label": "Sony Music",       "narm": "00"},
    {"ean": "0888072307902", "artist": "Miles Davis",            "title": "Sketches of Spain",           "date": date(2026, 1, 13), "imprint": "Columbia Records",    "label": "Sony Music",       "narm": "00"},
    {"ean": "0888072307919", "artist": "Miles Davis",            "title": "Milestones",                  "date": date(2026, 2, 10), "imprint": "Columbia Records",    "label": "Sony Music",       "narm": "00"},
    # John Coltrane
    {"ean": "0888072309203", "artist": "John Coltrane",          "title": "A Love Supreme",              "date": date(2026, 1, 20), "imprint": "Impulse! Records",    "label": "Verve Records",    "narm": "00"},
    {"ean": "0888072309210", "artist": "John Coltrane",          "title": "Blue Train",                  "date": date(2026, 1, 20), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    {"ean": "0888072309227", "artist": "John Coltrane",          "title": "Giant Steps",                 "date": date(2026, 2, 17), "imprint": "Atlantic Records",    "label": "Atlantic",         "narm": "00"},
    # Thelonious Monk
    {"ean": "0888072310415", "artist": "Thelonious Monk",        "title": "Brilliant Corners",           "date": date(2026, 1, 27), "imprint": "Riverside Records",   "label": "Fantasy Records",  "narm": "00"},
    {"ean": "0888072310422", "artist": "Thelonious Monk",        "title": "Monk's Music",                "date": date(2026, 1, 27), "imprint": "Riverside Records",   "label": "Fantasy Records",  "narm": "00"},
    # Clifford Brown
    {"ean": "0888072311443", "artist": "Clifford Brown",         "title": "Study in Brown",              "date": date(2026, 3, 3),  "imprint": "EmArcy Records",      "label": "Universal Music",  "narm": "00"},
    {"ean": "0888072311450", "artist": "Clifford Brown",         "title": "Clifford Brown with Strings", "date": date(2026, 3, 3),  "imprint": "EmArcy Records",      "label": "Universal Music",  "narm": "00"},
    # Sonny Rollins
    {"ean": "0888072312486", "artist": "Sonny Rollins",          "title": "Saxophone Colossus",          "date": date(2026, 3, 10), "imprint": "Prestige Records",    "label": "Fantasy Records",  "narm": "00"},
    {"ean": "0888072312493", "artist": "Sonny Rollins",          "title": "Way Out West",                "date": date(2026, 3, 10), "imprint": "Contemporary Records", "label": "Fantasy Records", "narm": "00"},
    # Wendell Harrison
    {"ean": "0820233171922", "artist": "Wendell Harrison & Tribe", "title": "An Afternoon in Harlem",  "date": date(2026, 1, 6),  "imprint": "",                    "label": "",                 "narm": "00"},
    {"ean": "0820233171939", "artist": "Wendell Harrison & Tribe", "title": "A Tribute to Pharoah Sanders", "date": date(2026, 1, 6), "imprint": "",               "label": "",                 "narm": "00"},
    {"ean": "0820233171946", "artist": "Wendell Harrison & Tribe", "title": "Birth of a Fossil",       "date": date(2026, 2, 3),  "imprint": "",                    "label": "",                 "narm": "00"},
    # RZA
    {"ean": "0829982311245", "artist": "RZA & Juice Crew",       "title": "Chamber Music 36",           "date": date(2026, 1, 6),  "imprint": "",                    "label": "",                 "narm": "02"},
    {"ean": "0829982311252", "artist": "RZA & Juice Crew",       "title": "Digital Bullet",             "date": date(2026, 1, 6),  "imprint": "",                    "label": "",                 "narm": "02"},
    # Pharoah Sanders
    {"ean": "0888072314473", "artist": "Pharoah Sanders",        "title": "Karma",                      "date": date(2026, 3, 17), "imprint": "Impulse! Records",    "label": "Verve Records",    "narm": "00"},
    {"ean": "0888072314480", "artist": "Pharoah Sanders",        "title": "Tauhid",                     "date": date(2026, 3, 17), "imprint": "Impulse! Records",    "label": "Verve Records",    "narm": "00"},
    # Charles Mingus
    {"ean": "0888072315518", "artist": "Charles Mingus",         "title": "The Black Saint and the Sinner Lady", "date": date(2026, 3, 24), "imprint": "Impulse! Records", "label": "Verve Records", "narm": "00"},
    {"ean": "0888072315525", "artist": "Charles Mingus",         "title": "Mingus Ah Um",               "date": date(2026, 3, 24), "imprint": "Columbia Records",    "label": "Sony Music",       "narm": "00"},
    # Ornette Coleman
    {"ean": "0888072316553", "artist": "Ornette Coleman",        "title": "The Shape of Jazz to Come",  "date": date(2026, 4, 1),  "imprint": "Atlantic Records",    "label": "Atlantic",         "narm": "00"},
    {"ean": "0888072316560", "artist": "Ornette Coleman",        "title": "Free Jazz",                  "date": date(2026, 4, 1),  "imprint": "Atlantic Records",    "label": "Atlantic",         "narm": "00"},
    # McCoy Tyner
    {"ean": "0888072317598", "artist": "McCoy Tyner",            "title": "The Real McCoy",             "date": date(2026, 4, 8),  "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Herbie Hancock
    {"ean": "0888072318632", "artist": "Herbie Hancock",         "title": "Maiden Voyage",              "date": date(2026, 4, 8),  "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    {"ean": "0888072318649", "artist": "Herbie Hancock",         "title": "Speak Like a Child",         "date": date(2026, 4, 15), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Wayne Shorter
    {"ean": "0888072319660", "artist": "Wayne Shorter",          "title": "Speak No Evil",              "date": date(2026, 4, 15), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    {"ean": "0888072319677", "artist": "Wayne Shorter",          "title": "JuJu",                       "date": date(2026, 4, 15), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Lee Morgan
    {"ean": "0888072320680", "artist": "Lee Morgan",             "title": "The Sidewinder",             "date": date(2026, 4, 22), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    {"ean": "0888072320697", "artist": "Lee Morgan",             "title": "Search for the New Land",    "date": date(2026, 4, 22), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Art Blakey
    {"ean": "0888072321717", "artist": "Art Blakey and the Jazz Messengers", "title": "Moanin'", "date": date(2026, 4, 22), "imprint": "Blue Note Records", "label": "Blue Note", "narm": "00"},
    {"ean": "0888072321724", "artist": "Art Blakey and the Jazz Messengers", "title": "The Freedom Rider", "date": date(2026, 4, 22), "imprint": "Blue Note Records", "label": "Blue Note", "narm": "00"},
    # Hank Mobley
    {"ean": "0888072322751", "artist": "Hank Mobley",            "title": "Soul Station",               "date": date(2026, 4, 29), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Andrew Hill
    {"ean": "0888072323757", "artist": "Andrew Hill",            "title": "Point of Departure",         "date": date(2026, 4, 29), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Eric Dolphy
    {"ean": "0888072324754", "artist": "Eric Dolphy",            "title": "Out to Lunch!",              "date": date(2026, 4, 29), "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Dexter Gordon
    {"ean": "0888072325750", "artist": "Dexter Gordon",          "title": "Go!",                        "date": date(2026, 5, 6),  "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
    # Jimmy Smith
    {"ean": "0888072326756", "artist": "Jimmy Smith",            "title": "The Sermon!",                "date": date(2026, 5, 6),  "imprint": "Blue Note Records",   "label": "Blue Note",        "narm": "00"},
]

# Rows 42–43: EAN conflict — same EAN appears twice with different artist_normalized
# (simulating two different scan sessions)
_EAN_CONFLICT_SCAN2 = [
    # "The Bill Evans Trio" vs original "Bill Evans Trio" — artist_normalized differs
    {"ean": "0753088935176", "artist": "The Bill Evans Trio",    "title": "Explorations",       "date": date(2026, 3, 1),  "imprint": "Riverside Records", "label": "Fantasy Records", "narm": "00"},
    # "RZA, Juice Crew" vs "RZA & Juice Crew" — artist_normalized SAME (both → "rza and juice crew")
    # But raw string differs → ARTIST_VARIANT  [row 44]
    {"ean": "0888072315518", "artist": "Charles Mingus Quartet", "title": "The Black Saint and the Sinner Lady", "date": date(2026, 4, 1),  "imprint": "Impulse! Records", "label": "Verve Records", "narm": "00"},
]

# Rows 44–45: Artist variant — same EAN, same artist_normalized, different raw strings
_ARTIST_VARIANTS = [
    {"ean": "0820233171922", "artist": "Wendell Harrison, Tribe", "title": "An Afternoon in Harlem", "date": date(2026, 3, 1), "imprint": "", "label": "", "narm": "00"},
    {"ean": "0829982311245", "artist": "RZA, Juice Crew",          "title": "Chamber Music 36",       "date": date(2026, 3, 1), "imprint": "", "label": "", "narm": "02"},
]

ALL_ROWS = _RELEASES + _EAN_CONFLICT_SCAN2 + _ARTIST_VARIANTS
assert len(ALL_ROWS) == 45, f"Expected 45 rows, got {len(ALL_ROWS)}"

# Assign ISNI/ISWC to ~40% each
ISNI_INDICES = set(range(0, 18))   # first 18 rows get ISNI
ISWC_INDICES = set(range(4, 22))   # rows 4–21 get ISWC (overlaps → some get both)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", default=DEMO_ORG_ID)
    parser.add_argument("--clear", action="store_true", help="Clear existing rows for this org first")
    args = parser.parse_args()

    org_id = args.org_id
    now = datetime.now(timezone.utc)

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()

    if args.clear:
        cur.execute("DELETE FROM catalog_index WHERE org_id = %s AND is_demo = false", (org_id,))
        print(f"Cleared existing rows for org {org_id}")

    # Create a fake scan_id to tie these together
    scan_id = str(uuid.uuid4())

    inserted = 0
    for i, rel in enumerate(ALL_ROWS):
        isni = ISNI_POOL[i % len(ISNI_POOL)] if i in ISNI_INDICES else None
        iswc = ISWC_POOL[i % len(ISWC_POOL)] if i in ISWC_INDICES else None

        cur.execute("""
            INSERT INTO catalog_index (
                ean, artist, artist_normalized, title, title_normalized,
                release_date, imprint, label, narm_config, isni, iswc,
                scan_id, org_id, is_demo, first_seen, last_seen, occurrence_count
            ) VALUES (
                %(ean)s, %(artist)s, %(artist_normalized)s, %(title)s, %(title_normalized)s,
                %(release_date)s, %(imprint)s, %(label)s, %(narm_config)s, %(isni)s, %(iswc)s,
                %(scan_id)s, %(org_id)s, false, %(first_seen)s, %(last_seen)s, 1
            )
        """, {
            "ean":               rel["ean"],
            "artist":            rel["artist"],
            "artist_normalized": normalize_artist(rel["artist"]),
            "title":             rel["title"],
            "title_normalized":  normalize_title(rel["title"]),
            "release_date":      rel["date"],
            "imprint":           rel.get("imprint", ""),
            "label":             rel.get("label", ""),
            "narm_config":       rel.get("narm", "00"),
            "isni":              isni,
            "iswc":              iswc,
            "scan_id":           None,  # no scan row — synthetic
            "org_id":            org_id,
            "first_seen":        now,
            "last_seen":         now,
        })
        inserted += 1
        print(f"  [{i+1:02d}/45] {rel['ean']} — {rel['artist'][:40]:<40} ISNI={'✓' if isni else '–'} ISWC={'✓' if iswc else '–'}")

    cur.close()
    conn.close()

    print(f"\nDone. Inserted {inserted} rows into catalog_index for org {org_id}")
    print(f"  EAN conflicts: 2 (Bill Evans Trio / Charles Mingus)")
    print(f"  Artist variants: 2 (Wendell Harrison, RZA)")
    print(f"  ISNI coverage: {len(ISNI_INDICES)}/45 ({len(ISNI_INDICES)*100//45}%)")
    print(f"  ISWC coverage: {len(ISWC_INDICES)}/45 ({len(ISWC_INDICES)*100//45}%)")


if __name__ == "__main__":
    main()
