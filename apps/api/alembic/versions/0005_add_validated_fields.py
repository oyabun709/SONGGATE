"""Add validated_fields to scans

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("validated_fields", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("scans", "validated_fields")
