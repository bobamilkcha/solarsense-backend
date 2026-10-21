import uuid
from datetime import UTC, datetime

from app.models import Project, SensorReading, Site
from app.modules.benchmark.client import PVGISError, fetch_monthly_irradiation_averages
from app.modules.benchmark.exceptions import BenchmarkUnavailableError
from app.modules.benchmark.schemas import BenchmarkResponse
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


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

        target_month = month or datetime.now(UTC).month

        avg_voltage, avg_current, reading_count = await self._device_averages(site_id, target_month)

        try:
            monthly_averages = await fetch_monthly_irradiation_averages(
                float(site.location_lat), float(site.location_lng)
            )
        except PVGISError as exc:
            raise BenchmarkUnavailableError from exc

        return BenchmarkResponse(
            site_id=site.id,
            month=target_month,
            device_reading_count=reading_count,
            device_avg_cell_voltage=avg_voltage,
            device_avg_cell_current=avg_current,
            satellite_avg_monthly_irradiation_kwh_m2=monthly_averages.get(target_month),
            satellite_source="PVGIS-ERA5",
        )

    async def _device_averages(
        self, site_id: uuid.UUID, month: int
    ) -> tuple[float | None, float | None, int]:
        stmt = select(
            func.avg(SensorReading.cell_voltage),
            func.avg(SensorReading.cell_current),
            func.count(SensorReading.id),
        ).where(
            SensorReading.site_id == site_id,
            func.extract("month", SensorReading.device_timestamp) == month,
        )
        avg_voltage, avg_current, count = (await self.db.execute(stmt)).one()
        return avg_voltage, avg_current, count
