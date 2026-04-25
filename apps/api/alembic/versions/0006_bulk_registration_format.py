"""Add BULK_REGISTRATION to submission_format enum

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL 12+ allows adding enum values outside a transaction
    op.execute("ALTER TYPE submission_format ADD VALUE IF NOT EXISTS 'BULK_REGISTRATION'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; this is intentionally a no-op.
    # To fully revert, recreate the type without BULK_REGISTRATION.
    pass
