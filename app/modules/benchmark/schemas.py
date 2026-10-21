import uuid

from pydantic import BaseModel, Field


class BenchmarkResponse(BaseModel):
    """Pairs a site's own device averages with PVGIS's satellite estimate.

    This is a raw comparison, not a verdict — converting cell_voltage/
    cell_current into a true irradiance (W/m^2) figure needs a calibration
    factor for the reference cell that hasn't been established yet, so the
    two sides aren't yet on the same unit. Left for the analyst/frontend to
    interpret until that calibration exists.
    """

    site_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    device_reading_count: int
    device_avg_cell_voltage: float | None
    device_avg_cell_current: float | None
    satellite_avg_monthly_irradiation_kwh_m2: float | None
    satellite_source: str
