"""Add device status/desired config and allow null sensor values in readings

Devices now report status (online, fw, publish interval) and accept remote
config. The firmware also sends null for a sensor that failed, so those
reading columns become nullable.

Revision ID: b7e3d9a1c5f2
Revises: f2a8c4e6b0d1
Create Date: 2026-11-09 00:00:02.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3d9a1c5f2"
down_revision: str | Sequence[str] | None = "f2a8c4e6b0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NULLABLE_READING_COLUMNS = ["ambient_temp", "humidity", "roll", "pitch", "heading"]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "devices", sa.Column("online", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("devices", sa.Column("fw", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("reported_publish_interval_s", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("status_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("desired_publish_interval_s", sa.Integer(), nullable=True))
    op.add_column(
        "devices", sa.Column("desired_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    for col in NULLABLE_READING_COLUMNS:
        op.alter_column("sensor_readings", col, existing_type=sa.Numeric(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Rows with a failed sensor can't satisfy NOT NULL; drop them first.
    cond = " OR ".join(f"{c} IS NULL" for c in NULLABLE_READING_COLUMNS)
    op.execute(f"DELETE FROM sensor_readings WHERE {cond}")
    for col in NULLABLE_READING_COLUMNS:
        op.alter_column("sensor_readings", col, existing_type=sa.Numeric(), nullable=False)
    for col in (
        "desired_requested_at",
        "desired_publish_interval_s",
        "status_at",
        "reported_publish_interval_s",
        "fw",
        "online",
    ):
        op.drop_column("devices", col)
