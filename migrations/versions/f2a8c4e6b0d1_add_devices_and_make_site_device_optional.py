"""Add devices table and make sites.device_id optional

`devices` records every device heard over MQTT so admins can pair one from a
list. A site's device_id becomes nullable so a device can be unpaired and
moved to another site.

Revision ID: f2a8c4e6b0d1
Revises: e4b7a2c9d1f3
Create Date: 2026-11-09 00:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a8c4e6b0d1"
down_revision: str | Sequence[str] | None = "e4b7a2c9d1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "devices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_rssi", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("sites", "device_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Unpaired sites have no device_id; give them a placeholder so the column
    # can go back to NOT NULL.
    op.execute("UPDATE sites SET device_id = 'unpaired-' || id WHERE device_id IS NULL")
    op.alter_column("sites", "device_id", existing_type=sa.String(), nullable=False)
    op.drop_table("devices")
