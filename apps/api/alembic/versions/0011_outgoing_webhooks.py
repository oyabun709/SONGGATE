"""Create webhook_endpoints and webhook_deliveries tables

webhook_endpoints: org-registered URLs that SONGGATE POSTs events to.
webhook_deliveries: delivery log (one row per attempted delivery).

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Registered endpoints ──────────────────────────────────────────────────
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id",      UUID(as_uuid=True), nullable=False),
        sa.Column("url",         sa.String(2048),    nullable=False),
        sa.Column("description", sa.String(255),     nullable=True),
        # HMAC-SHA256 signing secret (plaintext — org must keep it secret)
        sa.Column("secret",      sa.String(64),      nullable=False),
        # JSON array of event types, e.g. ["scan.complete", "scan.failed"]
        # NULL means "all events"
        sa.Column("events",      sa.JSON,            nullable=True),
        sa.Column("active",      sa.Boolean,         nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_webhook_endpoints_org_id", "webhook_endpoints", ["org_id"])

    # ── Delivery log ──────────────────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("endpoint_id", UUID(as_uuid=True),
                  sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event_type",  sa.String(100),  nullable=False),
        sa.Column("payload",     sa.JSON,         nullable=True),
        sa.Column("status_code", sa.Integer,      nullable=True),
        sa.Column("response_body", sa.Text,       nullable=True),
        sa.Column("attempt",     sa.Integer,      nullable=False,
                  server_default=sa.text("1")),
        # "pending" | "delivered" | "failed"
        sa.Column("status",      sa.String(20),   nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("error",       sa.Text,         nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_created_at",  "webhook_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_created_at",  table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_endpoint_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_endpoints_org_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
