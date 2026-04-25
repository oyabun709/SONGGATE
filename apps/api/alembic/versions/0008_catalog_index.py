"""Create catalog_index table and seed cross-catalog validation rules

The catalog_index table is the Phase 3 corpus: a persistent, cross-scan
store of all parsed releases from authenticated bulk registration scans.
Used for cross-catalog duplicate detection and artist disambiguation.

Cross-catalog rule IDs seeded here are FK-referenced by ScanResult rows
created when the cross-catalog checker fires during a bulk scan.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = datetime.now(timezone.utc).isoformat()

_CROSS_CATALOG_RULES = [
    {
        "id": "CROSS_CATALOG_EAN_CONFLICT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Cross-Catalog EAN Conflict — Artist",
        "description": (
            "EAN was previously submitted with a different artist name across catalog history. "
            "Conflicts cause identifier matching failures in downstream systems."
        ),
        "severity": "critical",
        "category": "identifiers",
        "fix_hint": (
            "Standardize release data across all submissions. "
            "Contact your distributor to reconcile historical records."
        ),
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "CROSS_CATALOG_TITLE_CONFLICT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Cross-Catalog EAN Conflict — Title",
        "description": "EAN was previously submitted with a different title across catalog history.",
        "severity": "warning",
        "category": "metadata",
        "fix_hint": "Standardize title capitalization across all submissions.",
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "CROSS_CATALOG_ISNI_CONFLICT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Cross-Catalog ISNI Conflict",
        "description": "EAN has conflicting ISNIs across catalog submissions.",
        "severity": "critical",
        "category": "identifiers",
        "fix_hint": (
            "A single artist may only have one ISNI. "
            "Verify the correct identifier at isni.org."
        ),
        "doc_url": "https://isni.org",
        "active": True,
        "version": "1.0.0",
    },
    {
        "id": "CROSS_CATALOG_ARTIST_VARIANT",
        "layer": "bulk_registration",
        "dsp": None,
        "title": "Artist Name Disambiguation",
        "description": (
            "Artist name has been submitted in multiple formats across catalog history "
            "(e.g. 'RZA & Juice Crew' vs 'RZA, Juice Crew'). "
            "Inconsistent formats reduce ISNI match rates."
        ),
        "severity": "warning",
        "category": "metadata",
        "fix_hint": (
            "Use a single canonical artist name format across all submissions. "
            "Inconsistent separators (& vs , vs and) reduce ISNI match rates "
            "in Luminate Data Enrichment and Quansic ArtistMatch."
        ),
        "doc_url": None,
        "active": True,
        "version": "1.0.0",
    },
]


def upgrade() -> None:
    # ── Create catalog_index table ────────────────────────────────────────────
    op.create_table(
        "catalog_index",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ean",               sa.String(13),  nullable=False),
        sa.Column("artist",            sa.String(500), nullable=True),
        sa.Column("artist_normalized", sa.String(500), nullable=True),
        sa.Column("title",             sa.String(500), nullable=True),
        sa.Column("title_normalized",  sa.String(500), nullable=True),
        sa.Column("release_date",      sa.Date,        nullable=True),
        sa.Column("imprint",           sa.String(255), nullable=True),
        sa.Column("label",             sa.String(255), nullable=True),
        sa.Column("narm_config",       sa.String(10),  nullable=True),
        sa.Column("isni",              sa.String(20),  nullable=True),
        sa.Column("iswc",              sa.String(20),  nullable=True),
        # scan_id FK — nullable so rows survive scan deletion
        sa.Column("scan_id", UUID(as_uuid=True),
                  sa.ForeignKey("scans.id", ondelete="SET NULL"), nullable=True),
        # org_id — no FK constraint; NULL allowed for demo-mode rows
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_demo",           sa.Boolean,     nullable=False,
                  server_default=sa.text("false")),
        sa.Column("first_seen",        sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("last_seen",         sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("occurrence_count",  sa.Integer,     nullable=False,
                  server_default=sa.text("1")),
    )

    op.create_index("ix_catalog_index_ean",               "catalog_index", ["ean"])
    op.create_index("ix_catalog_index_artist_normalized",  "catalog_index", ["artist_normalized"])
    op.create_index("ix_catalog_index_title_normalized",   "catalog_index", ["title_normalized"])
    op.create_index("ix_catalog_index_scan_id",            "catalog_index", ["scan_id"])
    op.create_index("ix_catalog_index_org_id",             "catalog_index", ["org_id"])

    # ── Seed cross-catalog validation rules ───────────────────────────────────
    conn = op.get_bind()
    for rule in _CROSS_CATALOG_RULES:
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
    op.drop_index("ix_catalog_index_org_id",            table_name="catalog_index")
    op.drop_index("ix_catalog_index_scan_id",           table_name="catalog_index")
    op.drop_index("ix_catalog_index_title_normalized",  table_name="catalog_index")
    op.drop_index("ix_catalog_index_artist_normalized", table_name="catalog_index")
    op.drop_index("ix_catalog_index_ean",               table_name="catalog_index")
    op.drop_table("catalog_index")

    conn = op.get_bind()
    for rule in _CROSS_CATALOG_RULES:
        conn.execute(sa.text("DELETE FROM rules WHERE id = :id"), {"id": rule["id"]})
