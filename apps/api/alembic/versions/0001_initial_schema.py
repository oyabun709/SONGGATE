"""Initial schema — organizations, releases, tracks, scans, scan_results, rules

Revision ID: 0001
Revises:
Create Date: 2026-04-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CORPUS_ANALYTICS_VIEW = """\
CREATE OR REPLACE VIEW corpus_analytics AS
SELECT
    r.id                                                          AS rule_id,
    r.layer,
    r.dsp,
    r.severity,
    r.category,
    r.title                                                       AS rule_title,
    r.active,
    COUNT(sr.id)                                                  AS total_evaluations,
    COUNT(sr.id) FILTER (WHERE sr.status = 'fail')               AS fail_count,
    COUNT(sr.id) FILTER (WHERE sr.status = 'warn')               AS warn_count,
    COUNT(sr.id) FILTER (WHERE sr.status = 'pass')               AS pass_count,
    COUNT(sr.id) FILTER (WHERE sr.resolved = TRUE)               AS resolved_count,
    ROUND(
        100.0
        * COUNT(sr.id) FILTER (WHERE sr.status = 'pass')
        / NULLIF(COUNT(sr.id), 0),
        2
    )                                                             AS pass_rate_pct,
    ROUND(
        100.0
        * COUNT(sr.id) FILTER (WHERE sr.resolved = TRUE AND sr.status <> 'pass')
        / NULLIF(COUNT(sr.id) FILTER (WHERE sr.status <> 'pass'), 0),
        2
    )                                                             AS resolution_rate_pct,
    MAX(sr.created_at)                                            AS last_evaluated_at
FROM rules r
LEFT JOIN scan_results sr ON sr.rule_id = r.id
GROUP BY r.id, r.layer, r.dsp, r.severity, r.category, r.title, r.active;
"""


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE org_tier AS ENUM ('starter', 'pro', 'enterprise');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE submission_format AS ENUM ('DDEX_ERN_43', 'DDEX_ERN_42', 'CSV', 'JSON');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE release_status AS ENUM ('pending', 'ingesting', 'ready', 'scanning', 'complete', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE scan_status AS ENUM ('queued', 'running', 'complete', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE scan_grade AS ENUM ('PASS', 'WARN', 'FAIL');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE result_status AS ENUM ('fail', 'warn', 'pass');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # ── organizations ─────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clerk_org_id", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column(
            "tier",
            postgresql.ENUM("starter", "pro", "enterprise", name="org_tier", create_type=False),
            nullable=False,
            server_default="starter",
        ),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_organizations_clerk_org_id", "organizations", ["clerk_org_id"])

    # ── rules ─────────────────────────────────────────────────────────────────
    # Created before releases/scans so FKs resolve in the correct order.
    op.create_table(
        "rules",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("layer", sa.String, nullable=False),
        sa.Column("dsp", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("fix_hint", sa.Text, nullable=True),
        sa.Column("doc_url", sa.String, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("version", sa.String, nullable=False, server_default="1.0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_rules_layer", "rules", ["layer"])
    op.create_index("ix_rules_dsp", "rules", ["dsp"])

    # ── releases ──────────────────────────────────────────────────────────────
    op.create_table(
        "releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("artist", sa.String, nullable=False),
        sa.Column("upc", sa.String(20), nullable=True),
        sa.Column("release_date", sa.Date, nullable=True),
        sa.Column(
            "submission_format",
            postgresql.ENUM(
                "DDEX_ERN_43", "DDEX_ERN_42", "CSV", "JSON",
                name="submission_format", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("raw_package_url", sa.String, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "ingesting", "ready", "scanning", "complete", "failed",
                name="release_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_releases_org_id", "releases", ["org_id"])
    op.create_index("ix_releases_external_id", "releases", ["external_id"])
    op.create_index("ix_releases_upc", "releases", ["upc"])

    # ── tracks ────────────────────────────────────────────────────────────────
    op.create_table(
        "tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("isrc", sa.String(12), nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("track_number", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.BigInteger, nullable=True),
        sa.Column("audio_url", sa.String, nullable=True),
        sa.Column("artwork_url", sa.String, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("acoustid_fingerprint", sa.String, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tracks_release_id", "tracks", ["release_id"])
    op.create_index("ix_tracks_isrc", "tracks", ["isrc"])

    # ── scans ─────────────────────────────────────────────────────────────────
    op.create_table(
        "scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("queued", "running", "complete", "failed", name="scan_status", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("readiness_score", sa.Float, nullable=True),
        sa.Column(
            "grade",
            postgresql.ENUM("PASS", "WARN", "FAIL", name="scan_grade", create_type=False),
            nullable=True,
        ),
        sa.Column("total_issues", sa.Integer, nullable=False, server_default="0"),
        sa.Column("critical_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("info_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("layers_run", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_scans_release_id", "scans", ["release_id"])
    op.create_index("ix_scans_org_id", "scans", ["org_id"])

    # ── scan_results ──────────────────────────────────────────────────────────
    op.create_table(
        "scan_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("layer", sa.String, nullable=False),
        sa.Column(
            "rule_id",
            sa.String,
            sa.ForeignKey("rules.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("fail", "warn", "pass", name="result_status", create_type=False),
            nullable=False,
        ),
        sa.Column("message", sa.String, nullable=False),
        sa.Column("field_path", sa.String, nullable=True),
        sa.Column("actual_value", sa.String, nullable=True),
        sa.Column("expected_value", sa.String, nullable=True),
        sa.Column("fix_hint", sa.String, nullable=True),
        sa.Column(
            "dsp_targets",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolution", sa.String, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Scalar indexes
    op.create_index("ix_scan_results_scan_id", "scan_results", ["scan_id"])
    op.create_index("ix_scan_results_track_id", "scan_results", ["track_id"])
    op.create_index("ix_scan_results_rule_id", "scan_results", ["rule_id"])
    op.create_index("ix_scan_results_layer", "scan_results", ["layer"])
    op.create_index("ix_scan_results_severity", "scan_results", ["severity"])
    op.create_index("ix_scan_results_resolved", "scan_results", ["resolved"])

    # GIN index on the dsp_targets array for containment queries (@>, &&, etc.)
    op.execute(
        "CREATE INDEX ix_scan_results_dsp_targets_gin "
        "ON scan_results USING GIN (dsp_targets)"
    )

    # ── corpus_analytics view ─────────────────────────────────────────────────
    op.execute(CORPUS_ANALYTICS_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS corpus_analytics")

    op.drop_table("scan_results")
    op.drop_table("scans")
    op.drop_table("tracks")
    op.drop_table("releases")
    op.drop_table("rules")
    op.drop_table("organizations")

    op.execute("DROP TYPE IF EXISTS result_status")
    op.execute("DROP TYPE IF EXISTS scan_grade")
    op.execute("DROP TYPE IF EXISTS scan_status")
    op.execute("DROP TYPE IF EXISTS release_status")
    op.execute("DROP TYPE IF EXISTS submission_format")
    op.execute("DROP TYPE IF EXISTS org_tier")
