import uuid
from datetime import datetime

from app.core.config.app_config import app_config
from app.models import Project, SensorReading, Site
from app.modules.benchmark.client import PVGISError, fetch_monthly_irradiation_averages
from app.modules.benchmark.exceptions import BenchmarkUnavailableError
from app.modules.benchmark.irradiation import LOCAL_TZ, daily_irradiation
from app.modules.benchmark.schemas import BenchmarkResponse
from app.modules.readings.exceptions import SiteNotFoundError
from app.modules.readings.irradiance import irradiance_wm2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# PVGIS monthly figures average over many years, so February includes leap years.
_DAYS_IN_MONTH = {1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}  # fmt: skip


class BenchmarkService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def compare(
        self, site_id: uuid.UUID, company_id: uuid.UUID | None, month: int | None = None
    ) -> BenchmarkResponse:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError

        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                # Site exists, just not in the caller's company — 404, not 403.
                raise SiteNotFoundError

        target_month = month or datetime.now(LOCAL_TZ).month
        isc = app_config.REFERENCE_CELL_ISC_A

        readings = await self._month_readings(site_id, target_month)
        count = len(readings)
        avg_voltage = sum(float(r.cell_voltage) for r in readings) / count if count else None
        avg_current = sum(float(r.cell_current) for r in readings) / count if count else None
        samples = [
            (r.device_timestamp, irradiance_wm2(float(r.cell_current), isc)) for r in readings
        ]
        avg_irradiance = sum(g for _, g in samples) / count if count else None

        complete_days = [d for d in daily_irradiation(samples) if d.is_complete]
        device_daily = (
            sum(d.kwh_m2 for d in complete_days) / len(complete_days) if complete_days else None
        )

        try:
            monthly_averages = await fetch_monthly_irradiation_averages(
                float(site.location_lat), float(site.location_lng)
            )
        except PVGISError as exc:
            raise BenchmarkUnavailableError from exc

        satellite_monthly = monthly_averages.get(target_month)
        satellite_daily = (
            satellite_monthly / _DAYS_IN_MONTH[target_month]
            if satellite_monthly is not None
            else None
        )
        ratio = (
            device_daily / satellite_daily if device_daily is not None and satellite_daily else None
        )

        return BenchmarkResponse(
            site_id=site.id,
            month=target_month,
            device_reading_count=count,
            device_avg_cell_voltage=avg_voltage,
            device_avg_cell_current=avg_current,
            device_avg_irradiance_wm2=avg_irradiance,
            device_complete_days=len(complete_days),
            device_avg_daily_irradiation_kwh_m2=device_daily,
            satellite_avg_monthly_irradiation_kwh_m2=satellite_monthly,
            satellite_avg_daily_irradiation_kwh_m2=satellite_daily,
            device_to_satellite_ratio=ratio,
            reference_cell_isc_a=isc,
            satellite_source="PVGIS-ERA5",
        )

    async def _month_readings(self, site_id: uuid.UUID, month: int):
        # Month in Malaysian local time, matching how days are grouped later.
        local_ts = func.timezone(str(LOCAL_TZ), SensorReading.device_timestamp)
        stmt = select(
            SensorReading.device_timestamp,
            SensorReading.cell_voltage,
            SensorReading.cell_current,
        ).where(
            SensorReading.site_id == site_id,
            func.extract("month", local_ts) == month,
        )
        return (await self.db.execute(stmt)).all()
