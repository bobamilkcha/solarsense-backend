"""Unique reading per site and device timestamp

The backend now uses a persistent MQTT session with QoS 1 ("at least once"),
so a reading can be delivered twice. The insert uses ON CONFLICT DO NOTHING on
this constraint. Existing exact duplicates (same site and timestamp) are removed
first, keeping the earliest-received row.

Revision ID: d1e5a7c3b9f4
Revises: b7e3d9a1c5f2
Create Date: 2026-11-10 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e5a7c3b9f4"
down_revision: str | Sequence[str] | None = "b7e3d9a1c5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DELETE FROM sensor_readings
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY site_id, device_timestamp ORDER BY received_at, id
                ) AS n
                FROM sensor_readings
            ) ranked
            WHERE n > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_sensor_readings_site_ts", "sensor_readings", ["site_id", "device_timestamp"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_sensor_readings_site_ts", "sensor_readings", type_="unique")
