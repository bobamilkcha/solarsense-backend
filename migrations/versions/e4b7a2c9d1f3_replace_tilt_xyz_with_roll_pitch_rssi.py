"""Replace tilt_x/y/z with roll, pitch and rssi on sensor_readings

The firmware now sends orientation as roll/pitch angles (degrees) plus Wi-Fi
signal strength, instead of raw accelerometer axes.

Existing rows are carried over: the mock data stored the tilt angle in
tilt_x and the sideways lean in tilt_y, so those become pitch and roll.

Revision ID: e4b7a2c9d1f3
Revises: 14d26794be0a
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b7a2c9d1f3"
down_revision: str | Sequence[str] | None = "14d26794be0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sensor_readings", sa.Column("roll", sa.Numeric(5, 2), nullable=True))
    op.add_column("sensor_readings", sa.Column("pitch", sa.Numeric(5, 2), nullable=True))
    op.add_column("sensor_readings", sa.Column("rssi", sa.SmallInteger(), nullable=True))
    op.execute(
        "UPDATE sensor_readings SET roll = LEAST(GREATEST(tilt_y, -180), 180), "
        "pitch = LEAST(GREATEST(tilt_x, -180), 180)"
    )
    op.alter_column("sensor_readings", "roll", nullable=False)
    op.alter_column("sensor_readings", "pitch", nullable=False)
    op.drop_column("sensor_readings", "tilt_x")
    op.drop_column("sensor_readings", "tilt_y")
    op.drop_column("sensor_readings", "tilt_z")


def downgrade() -> None:
    """Downgrade schema."""
    for name in ("tilt_x", "tilt_y", "tilt_z"):
        op.add_column("sensor_readings", sa.Column(name, sa.Numeric(6, 2), nullable=True))
    op.execute("UPDATE sensor_readings SET tilt_x = pitch, tilt_y = roll, tilt_z = 90 - pitch")
    for name in ("tilt_x", "tilt_y", "tilt_z"):
        op.alter_column("sensor_readings", name, nullable=False)
    op.drop_column("sensor_readings", "rssi")
    op.drop_column("sensor_readings", "pitch")
    op.drop_column("sensor_readings", "roll")
