import uuid

from app.models.base import Base, TimestampMixin
from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class Site(TimestampMixin, Base):
    __tablename__: str = "sites"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Null while no device is paired; set via PUT /sites/{id}/device.
    device_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    location_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    location_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
