import uuid
from datetime import datetime

from app.models.base import Base
from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class SensorReading(Base):
    __tablename__: str = "sensor_readings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    cell_voltage: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    cell_current: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    ambient_temp: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    humidity: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    tilt_x: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    tilt_y: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    tilt_z: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    heading: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    device_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
