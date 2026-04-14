"""Add Stripe billing fields to organizations

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-14 00:04:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("stripe_customer_id",          sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_subscription_id",       sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_subscription_status",   sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_price_id",              sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("stripe_subscription_item_id",  sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("current_period_start",         sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("current_period_end",           sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column(
        "scan_count_current_period", sa.Integer(), nullable=False, server_default="0"
    ))

    op.create_index("ix_orgs_stripe_customer_id",     "organizations", ["stripe_customer_id"],    unique=True)
    op.create_index("ix_orgs_stripe_subscription_id", "organizations", ["stripe_subscription_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_orgs_stripe_subscription_id", "organizations")
    op.drop_index("ix_orgs_stripe_customer_id",     "organizations")
    for col in [
        "scan_count_current_period",
        "current_period_end",
        "current_period_start",
        "stripe_subscription_item_id",
        "stripe_price_id",
        "stripe_subscription_status",
        "stripe_subscription_id",
        "stripe_customer_id",
    ]:
        op.drop_column("organizations", col)
