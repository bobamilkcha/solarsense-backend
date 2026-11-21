import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import SupportsFloat

from app.core.config.app_config import app_config
from app.models import Project, SensorReading, Site
from app.modules.readings.exceptions import (
    InvalidDateRangeError,
    SeriesTooLargeError,
    SiteNotFoundError,
    UnknownDeviceError,
)
from app.modules.readings.irradiance import irradiance_wm2
from app.modules.readings.schemas import (
    ReadingBucket,
    ReadingPayload,
    ReadingSeriesResponse,
    ReadingSeriesSummary,
)
from sqlalchemy import DateTime, Interval, cast, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Bucket widths (seconds) the series endpoint picks from when none is requested:
# the smallest that keeps the range at or under TARGET_BUCKETS points.
BUCKET_STEPS_S = (60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)
TARGET_BUCKETS = 1000
MAX_BUCKETS = 5000


def pick_bucket_s(start: datetime, end: datetime) -> int:
    span_s = (end - start).total_seconds()
    for step in BUCKET_STEPS_S:
        if span_s / step <= TARGET_BUCKETS:
            return step
    return BUCKET_STEPS_S[-1]


def _round(value: SupportsFloat | None, ndigits: int = 2) -> float | None:
    return None if value is None else round(float(value), ndigits)


def _irradiance(current: SupportsFloat | None) -> float | None:
    return None if current is None else round(irradiance_wm2(float(current)), 1)


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

    async def reading_series(
        self,
        site_id: uuid.UUID,
        company_id: uuid.UUID | None,
        start: datetime,
        end: datetime,
        bucket_s: int | None = None,
    ) -> ReadingSeriesResponse:
        """Readings in [start, end) averaged into fixed-width time buckets, for charts.

        Buckets are aligned to `start` (send local midnight to get buckets on
        local day boundaries) and empty buckets are left out, so gaps in the
        data stay visible as gaps.
        """
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if start >= end:
            raise InvalidDateRangeError
        bucket_s = bucket_s or pick_bucket_s(start, end)
        if (end - start).total_seconds() / bucket_s > MAX_BUCKETS:
            raise SeriesTooLargeError

        await self._authorized_site(site_id, company_id)

        r = SensorReading
        in_range = (r.site_id == site_id, r.device_timestamp >= start, r.device_timestamp < end)
        # Negative currents are ADC noise in the dark (see irradiance_wm2), so clamp
        # before averaging; irradiance is linear in current, so avg/max carry over.
        current = func.greatest(r.cell_current, 0)
        # Same formula as SensorReadingResponse.tilt_deg, clamped for float error.
        cos_tilt = func.cos(func.radians(r.roll)) * func.cos(func.radians(r.pitch))
        tilt = func.degrees(func.acos(func.least(1.0, func.greatest(-1.0, cos_tilt))))
        bucket = func.date_bin(
            cast(literal(timedelta(seconds=bucket_s)), Interval),
            r.device_timestamp,
            cast(literal(start), DateTime(timezone=True)),
        ).label("bucket")

        bucket_rows = (
            await self.db.execute(
                select(
                    bucket,
                    func.count(),
                    func.avg(current),
                    func.max(current),
                    func.avg(r.cell_voltage),
                    func.avg(r.ambient_temp),
                    func.min(r.ambient_temp),
                    func.max(r.ambient_temp),
                    func.avg(r.humidity),
                    func.min(r.humidity),
                    func.max(r.humidity),
                    func.avg(tilt),
                    func.avg(r.rssi),
                )
                .where(*in_range)
                .group_by(bucket)
                .order_by(bucket)
            )
        ).all()

        summary_row = (
            await self.db.execute(
                select(
                    func.count(),
                    func.min(r.device_timestamp),
                    func.max(r.device_timestamp),
                    func.max(current),
                    func.avg(r.ambient_temp),
                    func.min(r.ambient_temp),
                    func.max(r.ambient_temp),
                    func.avg(r.humidity),
                    func.min(r.humidity),
                    func.max(r.humidity),
                ).where(*in_range)
            )
        ).one()

        buckets = [
            ReadingBucket(
                bucket_start=row[0],
                count=row[1],
                irradiance_avg_wm2=_irradiance(row[2]) or 0.0,
                irradiance_max_wm2=_irradiance(row[3]) or 0.0,
                cell_voltage_avg=_round(row[4], 4) or 0.0,
                ambient_temp_avg=_round(row[5]),
                ambient_temp_min=_round(row[6]),
                ambient_temp_max=_round(row[7]),
                humidity_avg=_round(row[8]),
                humidity_min=_round(row[9]),
                humidity_max=_round(row[10]),
                tilt_deg_avg=_round(row[11]),
                rssi_avg=_round(row[12], 1),
            )
            for row in bucket_rows
        ]
        summary = ReadingSeriesSummary(
            count=summary_row[0],
            first_reading_at=summary_row[1],
            last_reading_at=summary_row[2],
            irradiance_max_wm2=_irradiance(summary_row[3]),
            ambient_temp_avg=_round(summary_row[4]),
            ambient_temp_min=_round(summary_row[5]),
            ambient_temp_max=_round(summary_row[6]),
            humidity_avg=_round(summary_row[7]),
            humidity_min=_round(summary_row[8]),
            humidity_max=_round(summary_row[9]),
        )
        return ReadingSeriesResponse(
            start=start, end=end, bucket_s=bucket_s, summary=summary, buckets=buckets
        )

    async def record_reading(self, device_id: str, payload: ReadingPayload) -> SensorReading | None:
        """Store a reading. Returns None if this site already has a reading at that
        device timestamp (an MQTT redelivery), leaving the existing row untouched."""
        site = await self.db.scalar(select(Site).where(Site.device_id == device_id))

        if site is None:
            raise UnknownDeviceError(device_id)

        stmt = (
            insert(SensorReading)
            .values(
                site_id=site.id,
                cell_voltage=payload.cell_voltage,
                cell_current=payload.cell_voltage / app_config.SHUNT_OHMS,
                ambient_temp=payload.ambient_temp,
                humidity=payload.humidity,
                roll=payload.roll,
                pitch=payload.pitch,
                heading=payload.heading,
                rssi=payload.rssi,
                device_timestamp=payload.timestamp or datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_sensor_readings_site_ts")
            .returning(SensorReading)
        )
        reading = await self.db.scalar(stmt)
        await self.db.commit()

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
