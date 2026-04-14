"""Add report_url and report_generated_at to scans

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-14 00:01:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("report_url", sa.String(), nullable=True))
    op.add_column("scans", sa.Column(
        "report_generated_at", sa.DateTime(timezone=True), nullable=True
    ))


def downgrade() -> None:
    op.drop_column("scans", "report_generated_at")
    op.drop_column("scans", "report_url")
