"""Add current_charges to tnb_bills

Revision ID: a3c9e1d4b2f0
Revises: 7fc1150ebe75
Create Date: 2026-10-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c9e1d4b2f0"
down_revision: str | Sequence[str] | None = "7fc1150ebe75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tnb_bills",
        sa.Column("current_charges", sa.Numeric(precision=10, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tnb_bills", "current_charges")
