"""Seed bulk registration validation rules into the rules table

These rule IDs are FK-referenced by ScanResult rows created during
authenticated bulk registration scans (POST /api/scans/bulk).

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = datetime.now(timezone.utc).isoformat()

_BULK_RULES = [
    # ── EAN ──────────────────────────────────────────────────────────────────
    {
        "id": "BULK_EAN_FORMAT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "EAN Format Validation",
        "description": "EAN must be exactly 13 digits and pass the GS1 check digit algorithm.",
        "severity": "critical",
        "category": "identifiers",
        "fix_hint": "Verify the EAN against your distributor's barcode allocation. EAN-13 barcodes must pass the GS1 check digit algorithm.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_EAN_DUPLICATE",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Duplicate EAN Detection",
        "description": "Each EAN must appear only once per bulk registration file.",
        "severity": "critical",
        "category": "identifiers",
        "fix_hint": "Each EAN must be unique. If this is the same release with variant formats, use distinct EANs per variant.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    # ── Dates ─────────────────────────────────────────────────────────────────
    {
        "id": "BULK_DATE_FORMAT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Release Date Format Validation",
        "description": "Release date must be in MMDDYY format and represent a valid calendar date.",
        "severity": "critical",
        "category": "metadata",
        "fix_hint": "Release dates must be in MMDDYY format, e.g. 041826 for April 18, 2026.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_DATE_FUTURE",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Far-Future Release Date",
        "description": "Release date is more than 6 months in the future.",
        "severity": "info",
        "category": "metadata",
        "fix_hint": "Releases registered more than 6 months in advance may be flagged by Luminate CONNECT for review.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    # ── Artist / title ────────────────────────────────────────────────────────
    {
        "id": "BULK_ARTIST_MISSING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Missing Artist Name",
        "description": "Artist name is missing or exceeds the maximum length.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Every release requires an artist name for DSP delivery and chart tracking.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_TITLE_MISSING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Missing Release Title",
        "description": "Release title is missing or exceeds the maximum length.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Every release requires a title for DSP delivery.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_ARTIST_INCONSISTENT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Artist Name Inconsistency",
        "description": "Duplicate EAN entries have inconsistent artist name formatting.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Standardize artist name format across all entries for this release.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_TITLE_INCONSISTENT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Title Inconsistency",
        "description": "Duplicate EAN entries have inconsistent title capitalization or content.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Standardize title capitalization across all entries for this release.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    # ── Rights ────────────────────────────────────────────────────────────────
    {
        "id": "BULK_IMPRINT_MISSING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Missing Imprint and Label",
        "description": "Both imprint and label are empty. Required for rights attribution and royalty routing.",
        "severity": "warning",
        "category": "rights",
        "fix_hint": "Add the imprint name and parent label. Required by Luminate for rights attribution and by distributors for royalty routing.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_NARM_UNKNOWN",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Unknown NARM Configuration Code",
        "description": "NARM configuration code is not a recognized value.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Known NARM codes: 00=Album, 02=Single, 04=EP, 05=Box Set, 06=Compilation.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    # ── ISNI (Phase 2) ────────────────────────────────────────────────────────
    {
        "id": "BULK_ISNI_MISSING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Missing ISNI",
        "description": "ISNI (International Standard Name Identifier) is not present for this artist.",
        "severity": "info",
        "category": "identifiers",
        "fix_hint": "Add ISNI for this artist. Look up or register at isni.org or use Luminate ArtistMatch.",
        "doc_url": "https://isni.org",
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_ISNI_FORMAT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Invalid ISNI Format",
        "description": "ISNI must be exactly 16 digits, optionally formatted with hyphens.",
        "severity": "warning",
        "category": "identifiers",
        "fix_hint": "Verify ISNI at isni.org or through Luminate Data Enrichment ArtistMatch service.",
        "doc_url": "https://isni.org",
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_ISNI_INCONSISTENT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "ISNI Inconsistent Across Entries",
        "description": "The same artist appears with ISNI in some entries and without it in others.",
        "severity": "warning",
        "category": "identifiers",
        "fix_hint": "Standardize ISNI across all entries for this artist.",
        "doc_url": "https://isni.org",
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_ISNI_CONFLICTING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Conflicting ISNI for Same Artist",
        "description": "Two or more different ISNIs are present for the same artist name — possible identity error.",
        "severity": "critical",
        "category": "identifiers",
        "fix_hint": "Verify the correct ISNI at isni.org. A single artist may only have one ISNI.",
        "doc_url": "https://isni.org",
        "active": True,
        "version": "1.0.0",
    },
    # ── ISWC (Phase 2) ────────────────────────────────────────────────────────
    {
        "id": "BULK_ISWC_MISSING",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Missing ISWC",
        "description": "ISWC (International Standard Musical Work Code) is not present for this release.",
        "severity": "info",
        "category": "identifiers",
        "fix_hint": "Add ISWC to enable WorksMatch linking in Luminate Data Enrichment. Register through your PRO (ASCAP, BMI, SESAC) or publisher.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "BULK_ISWC_FORMAT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Invalid ISWC Format",
        "description": "ISWC must follow the format T-XXXXXXXXX-C.",
        "severity": "warning",
        "category": "identifiers",
        "fix_hint": "Verify ISWC through your PRO or publisher. ISWCs are assigned by CISAC member organizations.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    for rule in _BULK_RULES:
        conn.execute(
            sa.text("""
                INSERT INTO rules (id, layer, dsp, title, description, severity,
                                   category, fix_hint, doc_url, active, version,
                                   created_at, updated_at)
                VALUES (:id, :layer, :dsp, :title, :description, :severity,
                        :category, :fix_hint, :doc_url, :active, :version,
                        :created_at, :updated_at)
                ON CONFLICT (id) DO NOTHING
            """),
            {**rule, "created_at": _NOW, "updated_at": _NOW},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for rule in _BULK_RULES:
        conn.execute(
            sa.text("DELETE FROM rules WHERE id = :id"),
            {"id": rule["id"]},
        )
