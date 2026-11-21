from datetime import datetime
from decimal import Decimal

from app.models.base import Base
from sqlalchemy import DateTime, Float, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class SatelliteIrradiance(Base):
    """Cached hourly satellite irradiance from Open-Meteo, one row per location-hour.

    Keyed by location (rounded to 0.01 degrees, finer than the ~5 km satellite
    pixel) rather than by site, so editing a site's location never serves
    another place's data. Past hours don't change, so each is fetched once.
    """

    __tablename__: str = "satellite_irradiance"
    lat: Mapped[Decimal] = mapped_column(Numeric(5, 2), primary_key=True)
    lng: Mapped[Decimal] = mapped_column(Numeric(5, 2), primary_key=True)
    # End of the hour; the value is the mean over the hour before it.
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ghi_wm2: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
