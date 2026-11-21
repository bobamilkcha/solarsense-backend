"""Add satellite_irradiance cache table

Hourly satellite irradiance from Open-Meteo, cached per location so the
same-day benchmark doesn't refetch past days.

Revision ID: a8f3c1e5d7b2
Revises: d1e5a7c3b9f4
Create Date: 2026-11-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3c1e5d7b2"
down_revision: str | Sequence[str] | None = "d1e5a7c3b9f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "satellite_irradiance",
        sa.Column("lat", sa.Numeric(5, 2), nullable=False),
        sa.Column("lng", sa.Numeric(5, 2), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ghi_wm2", sa.Float(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("lat", "lng", "period_end"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("satellite_irradiance")
