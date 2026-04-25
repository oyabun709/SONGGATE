"""Create api_usage_events table

Stores a log of every public API call, keyed on org_id and API key.
Used by /api/usage/summary and /api/usage/history endpoints.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id",     UUID(as_uuid=True), nullable=False),
        sa.Column("api_key_id", UUID(as_uuid=True), nullable=True),  # NULL for webhook delivery etc.
        sa.Column("endpoint",   sa.String(255),     nullable=False),
        sa.Column("method",     sa.String(10),      nullable=False),
        sa.Column("status_code", sa.Integer,        nullable=False),
        sa.Column("latency_ms", sa.Integer,         nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )

    op.create_index("ix_api_usage_events_org_id",    "api_usage_events", ["org_id"])
    op.create_index("ix_api_usage_events_created_at", "api_usage_events", ["created_at"])
    op.create_index("ix_api_usage_events_api_key_id", "api_usage_events", ["api_key_id"])


def downgrade() -> None:
    op.drop_index("ix_api_usage_events_api_key_id",  table_name="api_usage_events")
    op.drop_index("ix_api_usage_events_created_at",  table_name="api_usage_events")
    op.drop_index("ix_api_usage_events_org_id",       table_name="api_usage_events")
    op.drop_table("api_usage_events")
