"""Add api_keys, batch_jobs, and releases.archived_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-14 00:03:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── api_keys ──────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # ── batch_jobs ────────────────────────────────────────────────────────────
    op.create_table(
        "batch_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "running", "complete", "failed",
                name="batch_job_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("scan_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_batch_jobs_org_id", "batch_jobs", ["org_id"])

    # ── releases.archived_at ─────────────────────────────────────────────────
    op.add_column(
        "releases",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("releases", "archived_at")
    op.drop_table("batch_jobs")
    op.execute("DROP TYPE IF EXISTS batch_job_status")
    op.drop_index("ix_api_keys_key_hash", "api_keys")
    op.drop_index("ix_api_keys_key_prefix", "api_keys")
    op.drop_index("ix_api_keys_org_id", "api_keys")
    op.drop_table("api_keys")
