import uuid
from collections.abc import Sequence
from datetime import datetime

from app.models import Project, SensorReading, Site
from app.modules.readings.exceptions import (
    InvalidDateRangeError,
    SiteNotFoundError,
    UnknownDeviceError,
)
from app.modules.readings.schemas import ReadingPayload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SHUNT_RESISTANCE_OHMS = 10.0


class ReadingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_sites(self, company_id: uuid.UUID | None) -> Sequence[Site]:
        """`company_id=None` lists across every company (super_admin only)."""
        stmt = select(Site).order_by(Site.name)
        if company_id is not None:
            stmt = stmt.join(Project, Site.project_id == Project.id).where(
                Project.company_id == company_id
            )
        result = await self.db.scalars(stmt)
        return result.all()

    async def list_readings(
        self,
        site_id: uuid.UUID,
        company_id: uuid.UUID | None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[SensorReading]:
        await self._authorized_site(site_id, company_id)

        result = await self.db.scalars(
            select(SensorReading)
            .where(SensorReading.site_id == site_id)
            .order_by(SensorReading.device_timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.all()

    async def export_readings(
        self,
        site_id: uuid.UUID,
        company_id: uuid.UUID | None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Site, Sequence[SensorReading]]:
        """All readings in [start, end), oldest first."""
        if start is not None and end is not None and start >= end:
            raise InvalidDateRangeError

        site = await self._authorized_site(site_id, company_id)

        stmt = select(SensorReading).where(SensorReading.site_id == site_id)
        if start is not None:
            stmt = stmt.where(SensorReading.device_timestamp >= start)
        if end is not None:
            stmt = stmt.where(SensorReading.device_timestamp < end)
        result = await self.db.scalars(stmt.order_by(SensorReading.device_timestamp))
        return site, result.all()

    async def record_reading(self, device_id: str, payload: ReadingPayload) -> SensorReading:
        site = await self.db.scalar(select(Site).where(Site.device_id == device_id))

        if site is None:
            raise UnknownDeviceError(device_id)

        reading = SensorReading(
            site_id=site.id,
            cell_voltage=payload.cell_voltage,
            cell_current=payload.cell_voltage / SHUNT_RESISTANCE_OHMS,
            ambient_temp=payload.ambient_temp,
            humidity=payload.humidity,
            tilt_x=payload.tilt_x,
            tilt_y=payload.tilt_y,
            tilt_z=payload.tilt_z,
            heading=payload.heading,
            device_timestamp=payload.timestamp,
        )

        self.db.add(reading)
        await self.db.commit()
        await self.db.refresh(reading)

        return reading

    async def _authorized_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError

        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                # Site exists, just not in the caller's company — 404, not 403,
                # so we don't leak which device_ids/site_ids belong to others.
                raise SiteNotFoundError

        return site
