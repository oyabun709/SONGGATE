"""Create weekly_submissions table

Tracks the number of releases and scan sessions submitted per ISO week,
per org. Used to render the 12-week submission calendar on the catalog
dashboard.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_submissions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        # org_id — no FK; NULL not allowed
        sa.Column("org_id",          UUID(as_uuid=True), nullable=False),
        # ISO week fields
        sa.Column("week_start",      sa.Date,    nullable=False),  # Monday of the ISO week
        sa.Column("iso_year",        sa.Integer, nullable=False),
        sa.Column("iso_week",        sa.Integer, nullable=False),
        # Counts
        sa.Column("release_count",   sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("scan_count",      sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("critical_count",  sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("warning_count",   sa.Integer, nullable=False, server_default=sa.text("0")),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )

    # One row per (org, week)
    op.create_unique_constraint(
        "uq_weekly_submissions_org_week",
        "weekly_submissions",
        ["org_id", "iso_year", "iso_week"],
    )
    op.create_index("ix_weekly_submissions_org_id",    "weekly_submissions", ["org_id"])
    op.create_index("ix_weekly_submissions_week_start", "weekly_submissions", ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_weekly_submissions_week_start", table_name="weekly_submissions")
    op.drop_index("ix_weekly_submissions_org_id",     table_name="weekly_submissions")
    op.drop_constraint("uq_weekly_submissions_org_week", "weekly_submissions")
    op.drop_table("weekly_submissions")
