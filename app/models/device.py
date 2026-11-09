from datetime import datetime

from app.models.base import Base
from sqlalchemy import DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class Device(Base):
    """A device the backend has heard from over MQTT, paired or not.

    Pairing itself lives on `Site.device_id`; this table only records that a
    device exists and when it was last online, so admins can pick it from a
    list instead of typing its ID.
    """

    __tablename__: str = "devices"
    # The ID from the MQTT topic, e.g. "solarsense-38BB0B71FE68" (MAC-based).
    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_rssi: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
