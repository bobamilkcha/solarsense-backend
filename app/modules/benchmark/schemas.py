import uuid
from typing import Literal

from pydantic import BaseModel, Field

PeriodName = Literal["morning", "midday", "afternoon"]


class SameDayPeriod(BaseModel):
    """Device vs satellite for one part of the day (local hours [start_hour, end_hour))."""

    period: PeriodName
    start_hour: int
    end_hour: int
    hours: int = Field(description="Matched device hours in this period")
    device_kwh_m2: float
    satellite_kwh_m2: float
    ratio: float | None = Field(description="device / satellite; null if too little data")


class SameDayBenchmark(BaseModel):
    """Device vs satellite irradiance for the SAME hours, so weather cancels out.

    Only daylight clock hours (07:00-19:00) the device covered almost fully are
    used, each compared with the satellite's figure for that hour. ~1.0 means
    no shading; well below 1.0 means local shading. `periods` shows when in the
    day it happens.
    """

    ratio: float | None = Field(description="device / satellite; null if too little data")
    days: int = Field(description="Days with at least one matched hour")
    hours: int = Field(description="Matched device hours")
    device_kwh_m2: float
    satellite_kwh_m2: float
    periods: list[SameDayPeriod]
    source: str


class BenchmarkResponse(BaseModel):
    """Pairs a site's own device measurements with PVGIS's satellite estimate.

    Device readings are converted to irradiance using the reference cell's
    short-circuit current (`reference_cell_isc_a`), then integrated per day so
    both sides are in kWh/m^2/day. Only "complete" days (most of the daylight
    window covered by readings) count toward the device's daily average.

    PVGIS figures are for a horizontal surface, so the ratio is only
    meaningful when the reference cell lies flat during measurement.
    """

    site_id: uuid.UUID
    month: int = Field(ge=1, le=12)
    device_reading_count: int
    device_avg_cell_voltage: float | None
    device_avg_cell_current: float | None
    device_avg_irradiance_wm2: float | None
    device_complete_days: int
    device_avg_daily_irradiation_kwh_m2: float | None
    satellite_avg_monthly_irradiation_kwh_m2: float | None
    satellite_avg_daily_irradiation_kwh_m2: float | None
    # device / satellite daily irradiation: ~1.0 means the site gets what the
    # satellite expects; well below 1.0 suggests local shading.
    device_to_satellite_ratio: float | None
    reference_cell_isc_a: float
    satellite_source: str
    same_day: SameDayBenchmark | None = Field(
        description=(
            "Device vs satellite for the same hours (weather-corrected). Null when no "
            "hour could be matched or the satellite service is unreachable."
        )
    )
