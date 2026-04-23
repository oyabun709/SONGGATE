"""
Seed the SONGGATE demo account.

Creates a demo organization and 5 pre-completed scans with realistic
issues, scores, and fix hints — ready for the Luminate partnership call.

Usage:
    cd /Users/andrewanglin/ropqa/apps/api
    python ../../scripts/seed_demo_account.py

The script is idempotent — running it again will not create duplicates.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Add API source root to path ───────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

import asyncpg  # noqa: E402  (loaded after sys.path fix)
from dotenv import load_dotenv  # noqa: E402
import os  # noqa: E402

load_dotenv(Path(__file__).parent.parent / "apps" / "api" / ".env.local")

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Demo org config ───────────────────────────────────────────────────────────

DEMO_CLERK_ORG_ID = "org_demo_songgate_2026"
DEMO_ORG_NAME     = "SONGGATE Demo"
DEMO_ORG_ID       = "00000000-0000-0000-0000-000000000001"   # stable UUID for demo org

# ── Pre-seeded scans ──────────────────────────────────────────────────────────

DEMO_SCANS = [
    {
        "release_title":  "Luminous Decay",
        "release_artist": "Nova Crest",
        "upc":            "886447117125",
        "score":          42.0,
        "grade":          "FAIL",
        "critical_count": 4,
        "warning_count":  2,
        "info_count":     1,
        "total_issues":   7,
        "issues": [
            {
                "layer":    "ddex",
                "severity": "critical",
                "message":  "Track 3 ISRC 'USRC11607841X' is malformed — must follow CC-XXX-YY-NNNNN format.",
                "fix_hint": "Correct the ISRC to US-RC1-16-07841 and resubmit the DDEX package. All ISRCs must comply with ISO 3901.",
                "dsp_targets": ["spotify", "apple_music", "amazon"],
            },
            {
                "layer":    "metadata",
                "severity": "critical",
                "message":  "Track 2 'Refraction' is missing a MusicPublisher contributor.",
                "fix_hint": "Add a Contributor element with Role=MusicPublisher to Track 2. Required by Spotify, Apple Music, and Amazon for royalty processing.",
                "dsp_targets": ["spotify", "apple_music", "amazon", "deezer"],
            },
            {
                "layer":    "artwork",
                "severity": "critical",
                "message":  "Cover artwork is 2000×2000 px — below the 3000×3000 px minimum required by Spotify, Apple Music, and Amazon.",
                "fix_hint": "Resize artwork to at least 3000×3000 px in JPEG or PNG format. Many DSPs will auto-reject artwork below this resolution.",
                "dsp_targets": ["spotify", "apple_music", "amazon"],
            },
            {
                "layer":    "fraud",
                "severity": "critical",
                "message":  "Track 3 'Sleep Sounds Relaxation' (45s) matches music spam pattern: short duration + functional keyword title.",
                "fix_hint": "If this is intentional ambient content, add SubGenre=SoundEffects and verify the content is not generated padding. Streams under 30s do not qualify for royalties on most platforms.",
                "dsp_targets": [],
            },
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "Track 3 duration is 45 seconds — below the 60-second minimum for Spotify and Apple Music royalty eligibility.",
                "fix_hint": "Extend the track to at least 60 seconds or mark it as a sound effect / bonus content to avoid distribution rejection.",
                "dsp_targets": ["spotify", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "warning",
                "message":  "Release date 2026-06-01 is more than 90 days in the future — some DSPs restrict pre-order windows.",
                "fix_hint": "Confirm Spotify and Apple Music pre-order windows (max 90 days). Consider adjusting release date or enabling pre-save campaigns.",
                "dsp_targets": ["spotify", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "Genre 'Indie Electronic' is not in Spotify's canonical genre taxonomy.",
                "fix_hint": "Map to the closest Spotify genre (e.g. 'Electronic', 'Indie Pop') to improve discovery and playlist placement.",
                "dsp_targets": ["spotify"],
            },
        ],
    },
    {
        "release_title":  "After Hours",
        "release_artist": "The Meridian",
        "upc":            "886447118222",
        "score":          71.0,
        "grade":          "WARN",
        "critical_count": 0,
        "warning_count":  4,
        "info_count":     2,
        "total_issues":   6,
        "issues": [
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "Integrated loudness is -7.2 LUFS — 7 dB louder than Spotify's -14 LUFS target. Will be normalised down, reducing dynamic impact.",
                "fix_hint": "Re-master to target -14 LUFS integrated / -1 dBTP true peak for Spotify delivery. Apple Music targets -16 LUFS for lossless.",
                "dsp_targets": ["spotify", "apple_music", "tidal"],
            },
            {
                "layer":    "metadata",
                "severity": "warning",
                "message":  "P-Line year (2025) does not match release date year (2026).",
                "fix_hint": "Update the P-Line to (P) 2026 to match the release year. Year mismatches trigger metadata rejection at some distributors.",
                "dsp_targets": ["spotify", "apple_music", "amazon"],
            },
            {
                "layer":    "metadata",
                "severity": "warning",
                "message":  "UPC '88644711822' is 11 digits — expected 12 or 13 digits.",
                "fix_hint": "Verify the UPC with your barcode provider. Standard UPCs are 12 digits (UPC-A) or 13 digits (EAN-13).",
                "dsp_targets": ["spotify", "apple_music", "amazon", "tidal", "deezer"],
            },
            {
                "layer":    "artwork",
                "severity": "warning",
                "message":  "Artwork color mode is CMYK — DSPs require RGB for digital delivery.",
                "fix_hint": "Convert artwork to RGB color mode in Photoshop or Lightroom before resubmitting. CMYK artwork will display incorrectly on all DSPs.",
                "dsp_targets": ["spotify", "apple_music", "amazon", "tidal"],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "Track 2 has no explicit content advisory flag. Verify lyrics.",
                "fix_hint": "Review Track 2 for explicit content. If present, set ExplicitContentWarning=Explicit to avoid metadata rejection on family-friendly profiles.",
                "dsp_targets": ["spotify", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "Language code is not set — defaults to 'en'.",
                "fix_hint": "Set LanguageCode to the primary vocal language. Required for non-English content on Apple Music, Tidal, and QQ Music.",
                "dsp_targets": ["apple_music", "tidal"],
            },
        ],
    },
    {
        "release_title":  "Golden State",
        "release_artist": "Asha Voss",
        "upc":            "886447119333",
        "score":          88.0,
        "grade":          "PASS",
        "critical_count": 0,
        "warning_count":  0,
        "info_count":     3,
        "total_issues":   3,
        "issues": [
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "No ISWC registered for the composition. Recommended for songwriter royalty tracking.",
                "fix_hint": "Register the composition with your PRO (ASCAP, BMI, SESAC) and include the ISWC in the metadata to improve royalty reconciliation.",
                "dsp_targets": [],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "MusicBrainz: artist name 'Asha Voss' matches 'Asha Voss' with 94% confidence. Consider linking MB artist ID for enrichment.",
                "fix_hint": "Link the MusicBrainz artist ID to improve metadata enrichment and discoverability on Tidal and Apple Music.",
                "dsp_targets": ["tidal", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "Dolby Atmos spatial audio not declared. If available, declare for Apple Music and Tidal premium placement.",
                "fix_hint": "If a Dolby Atmos mix is available, add the has_dolby_atmos flag and submit the ADM WAV file to Apple Music for Spatial Audio badge eligibility.",
                "dsp_targets": ["apple_music", "tidal"],
            },
        ],
    },
    {
        "release_title":  "Echoes of You",
        "release_artist": "Westfield",
        "upc":            "886447120444",
        "score":          34.0,
        "grade":          "FAIL",
        "critical_count": 5,
        "warning_count":  1,
        "info_count":     0,
        "total_issues":   6,
        "issues": [
            {
                "layer":    "fraud",
                "severity": "critical",
                "message":  "ISRC USPR12600001 already assigned to a different release in your catalog ('Luminous Decay — Nova Crest').",
                "fix_hint": "Request new ISRCs from your ISRC registrar. Each unique recording must have a unique ISRC — reuse constitutes metadata fraud and will result in distribution suspension.",
                "dsp_targets": ["spotify", "apple_music", "amazon", "tidal"],
            },
            {
                "layer":    "fraud",
                "severity": "critical",
                "message":  "3 of 4 track titles match functional music spam keywords (sleep, relax, focus, ambient).",
                "fix_hint": "Review track titles. Functional music spam is a known fraud vector. If the content is legitimately therapeutic/ambient, add SubGenre and ContentAdvisory metadata to distinguish it.",
                "dsp_targets": [],
            },
            {
                "layer":    "fraud",
                "severity": "critical",
                "message":  "All 4 tracks have identical duration (180s) — uniformity is a strong indicator of generated/padded content.",
                "fix_hint": "Review recordings for authenticity. Identical durations across an album are flagged by Spotify's fraud detection. Natural performances will have slight timing variations.",
                "dsp_targets": ["spotify"],
            },
            {
                "layer":    "ddex",
                "severity": "critical",
                "message":  "MessageHeader/MessageCreatedDateTime is missing.",
                "fix_hint": "Add MessageCreatedDateTime to the MessageHeader element. Format: ISO 8601 (e.g. 2026-04-22T10:00:00Z). Required for DDEX ERN 4.3 compliance.",
                "dsp_targets": [],
            },
            {
                "layer":    "metadata",
                "severity": "critical",
                "message":  "Label name is missing on the release.",
                "fix_hint": "Add the LabelName element to the ReleaseDetailsByTerritory. Required by all major DSPs for contract and royalty attribution.",
                "dsp_targets": ["spotify", "apple_music", "amazon", "tidal", "deezer"],
            },
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "True peak exceeds -1 dBTP on Track 2 (+0.3 dBTP detected).",
                "fix_hint": "Apply a true peak limiter set to -1 dBTP and re-export. Clipping above -1 dBTP will cause codec artifacts on Apple AAC and Spotify Ogg encoding.",
                "dsp_targets": ["spotify", "apple_music", "amazon"],
            },
        ],
    },
    {
        "release_title":  "Neon City",
        "release_artist": "DJ Calloway",
        "upc":            "886447121555",
        "score":          65.0,
        "grade":          "WARN",
        "critical_count": 0,
        "warning_count":  5,
        "info_count":     1,
        "total_issues":   6,
        "issues": [
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "Track 1 'Neon City (Club Mix)' integrated loudness is -6.1 LUFS — significantly louder than DSP targets.",
                "fix_hint": "Target -14 LUFS for Spotify, -16 LUFS for Apple Music Lossless. Excessive loudness is normalised down, degrading dynamic range. Consider separate masters for streaming vs. club use.",
                "dsp_targets": ["spotify", "apple_music"],
            },
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "Track 3 'After Dark' integrated loudness is -7.8 LUFS.",
                "fix_hint": "Re-master Track 3 to target -14 LUFS / -1 dBTP. See SONGGATE Audio Mastering Guidelines for streaming-optimised export settings.",
                "dsp_targets": ["spotify", "apple_music", "tidal"],
            },
            {
                "layer":    "audio",
                "severity": "warning",
                "message":  "Sample rate is 44.1 kHz — Tidal Masters and Apple Music Lossless require 48 kHz or higher.",
                "fix_hint": "Deliver a 48 kHz / 24-bit version alongside the standard 44.1 kHz master for Hi-Res platform eligibility.",
                "dsp_targets": ["tidal", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "warning",
                "message":  "Track 4 'City Lights (feat. Alara)' — featured artist 'Alara' is not listed as a Contributor with Role=FeaturedArtist.",
                "fix_hint": "Add Alara as a Contributor with Role=FeaturedArtist on Track 4. Featured artists must be declared separately from the primary DisplayArtist for proper royalty splits.",
                "dsp_targets": ["spotify", "apple_music", "amazon", "tidal"],
            },
            {
                "layer":    "metadata",
                "severity": "warning",
                "message":  "C-Line on Track 2 reads '© 2025 Calloway Music' but release year is 2026.",
                "fix_hint": "Update C-Line to © 2026 Calloway Music to match the release year. Year mismatches cause rejection at some distributors.",
                "dsp_targets": ["spotify", "apple_music"],
            },
            {
                "layer":    "metadata",
                "severity": "info",
                "message":  "BPM metadata is missing on all tracks. Recommended for Spotify and Beatport editorial placement.",
                "fix_hint": "Add BPM values to each track's metadata. For electronic/dance releases, accurate BPM improves algorithmic playlist placement on Spotify and Beatport.",
                "dsp_targets": ["spotify"],
            },
        ],
    },
]


# ── Seeding logic ─────────────────────────────────────────────────────────────

async def seed() -> None:
    print("Connecting to database…")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # ── 1. Upsert demo org ────────────────────────────────────────────────
        print("Upserting demo organization…")
        await conn.execute("""
            INSERT INTO organizations (id, clerk_org_id, name, tier, settings, created_at, scan_count_current_period)
            VALUES ($1, $2, $3, 'pro', $4, NOW(), 0)
            ON CONFLICT (clerk_org_id) DO UPDATE
              SET name = EXCLUDED.name,
                  tier = EXCLUDED.tier,
                  settings = EXCLUDED.settings
        """,
            uuid.UUID(DEMO_ORG_ID),
            DEMO_CLERK_ORG_ID,
            DEMO_ORG_NAME,
            '{"is_test": true, "is_demo": true}',
        )
        print(f"  ✓ Org: {DEMO_ORG_NAME} ({DEMO_CLERK_ORG_ID})")

        # ── 2. Seed each demo scan ────────────────────────────────────────────
        for i, scan_def in enumerate(DEMO_SCANS):
            rel_id  = str(uuid.uuid5(uuid.UUID(DEMO_ORG_ID), f"release-{i}"))
            scan_id = str(uuid.uuid5(uuid.UUID(DEMO_ORG_ID), f"scan-{i}"))
            days_ago = (len(DEMO_SCANS) - i) * 3   # space them 3 days apart

            created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)

            # Release
            await conn.execute("""
                INSERT INTO releases (
                    id, org_id, title, artist, upc,
                    submission_format, status, metadata_, created_at
                ) VALUES ($1, $2, $3, $4, $5, 'DDEX_ERN_43', 'complete', $6, $7)
                ON CONFLICT (id) DO UPDATE
                  SET title  = EXCLUDED.title,
                      artist = EXCLUDED.artist
            """,
                uuid.UUID(rel_id),
                uuid.UUID(DEMO_ORG_ID),
                scan_def["release_title"],
                scan_def["release_artist"],
                scan_def["upc"],
                '{}',
                created_at,
            )

            # Scan
            await conn.execute("""
                INSERT INTO scans (
                    id, release_id, org_id, status, readiness_score, grade,
                    critical_count, warning_count, info_count, total_issues,
                    layers_run, started_at, completed_at, created_at
                ) VALUES ($1, $2, $3, 'complete', $4, $5, $6, $7, $8, $9, $10, $11, $11, $11)
                ON CONFLICT (id) DO UPDATE
                  SET readiness_score = EXCLUDED.readiness_score,
                      grade           = EXCLUDED.grade,
                      status          = EXCLUDED.status
            """,
                uuid.UUID(scan_id),
                uuid.UUID(rel_id),
                uuid.UUID(DEMO_ORG_ID),
                scan_def["score"],
                scan_def["grade"],
                scan_def["critical_count"],
                scan_def["warning_count"],
                scan_def["info_count"],
                scan_def["total_issues"],
                ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"],
                created_at,
            )

            # Scan results
            for j, issue in enumerate(scan_def["issues"]):
                result_id = str(uuid.uuid5(uuid.UUID(scan_id), f"result-{j}"))
                rule_id   = f"demo.{issue['layer']}.{j:02d}"
                severity  = issue["severity"]
                status    = "fail" if severity == "critical" else "warn"

                # Upsert rule
                await conn.execute("""
                    INSERT INTO rules (id, layer, severity, title, category, version, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $2, '1.0.0', NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """,
                    rule_id,
                    issue["layer"],
                    severity,
                    issue["message"][:120],
                )

                # Upsert result
                await conn.execute("""
                    INSERT INTO scan_results (
                        id, scan_id, layer, rule_id, severity, status,
                        message, fix_hint, dsp_targets, resolved, metadata_, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, false, '{}', $10)
                    ON CONFLICT (id) DO UPDATE
                      SET message  = EXCLUDED.message,
                          fix_hint = EXCLUDED.fix_hint
                """,
                    uuid.UUID(result_id),
                    uuid.UUID(scan_id),
                    issue["layer"],
                    rule_id,
                    severity,
                    status,
                    issue["message"],
                    issue["fix_hint"],
                    issue["dsp_targets"],
                    created_at,
                )

            print(f"  ✓ Scan {i+1}/5: {scan_def['release_title']} — "
                  f"{scan_def['grade']} ({scan_def['score']}) "
                  f"[{scan_def['total_issues']} issues]")

        print()
        print("═" * 60)
        print("Demo account seeded successfully.")
        print()
        print("  Org ID:     ", DEMO_ORG_ID)
        print("  Clerk org:  ", DEMO_CLERK_ORG_ID)
        print("  Login:       demo@songgate.io")
        print("  Password:    SonggateDEMO2026!")
        print()
        print("NOTE: You must create the Clerk user for demo@songgate.io")
        print("      and assign them to clerk_org_id =", DEMO_CLERK_ORG_ID)
        print("      via the Clerk dashboard.")
        print("═" * 60)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
