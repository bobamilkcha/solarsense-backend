"""Compare device readings with satellite irradiance for the same hours.

The PVGIS benchmark compares against a long-term monthly average, so a rainy
week looks like a shaded site. Here each clock hour the device fully measured
is paired with the satellite's figure for that same hour, so weather cancels
out and what's left is mostly local shading. Hours the device missed simply
drop out of both sides, so partial days still count.

Splitting the ratio by time of day shows *when* a site is shaded (e.g. a
building to the east blocks the morning sun).
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.core.logging.service import get_log_service
from app.models import SatelliteIrradiance
from app.modules.benchmark import open_meteo
from app.modules.benchmark.irradiation import DAYLIGHT_END, DAYLIGHT_START, LOCAL_TZ, MAX_GAP
from app.modules.benchmark.schemas import PeriodName, SameDayBenchmark, SameDayPeriod
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_log_service()

HOUR = timedelta(hours=1)
# An hour counts only if the device's readings cover nearly all of it.
MIN_HOUR_COVERAGE = 0.9
# Below this much satellite energy (Wh/m^2) a ratio is mostly noise.
MIN_SATELLITE_WH_TOTAL = 1000.0
MIN_SATELLITE_WH_PERIOD = 300.0
# Local hours [start, end) for the time-of-day breakdown.
PERIODS: tuple[tuple[PeriodName, int, int], ...] = (
    ("morning", 7, 11),
    ("midday", 11, 14),
    ("afternoon", 14, 19),
)
# Satellite values this recent may still be missing or provisional: don't cache them.
SETTLE_TIME = timedelta(hours=3)

Sample = tuple[datetime, float]  # (timezone-aware timestamp, irradiance W/m^2)


def hourly_device_energy(samples: Iterable[Sample]) -> dict[datetime, tuple[float, float]]:
    """Device energy per clock hour: {hour end (UTC): (Wh/m^2, seconds covered)}.

    Same trapezoid rule as `daily_irradiation`: consecutive samples further
    apart than MAX_GAP aren't bridged. Segments crossing an hour boundary are
    split there, interpolating the irradiance at the boundary.
    """
    ordered = sorted((ts.astimezone(UTC), g) for ts, g in samples)
    hours: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for (t1, g1), (t2, g2) in zip(ordered, ordered[1:], strict=False):
        span = (t2 - t1).total_seconds()
        if span <= 0 or t2 - t1 > MAX_GAP:
            continue
        a, ga = t1, g1
        while a < t2:
            hour_end = a.replace(minute=0, second=0, microsecond=0) + HOUR
            b = min(hour_end, t2)
            gb = g1 + (g2 - g1) * (b - t1).total_seconds() / span
            seconds = (b - a).total_seconds()
            hours[hour_end][0] += (ga + gb) / 2 * seconds / 3600
            hours[hour_end][1] += seconds
            a, ga = b, gb
    return {end: (wh, covered) for end, (wh, covered) in hours.items()}


def _local_start_hour(hour_end: datetime) -> int:
    return (hour_end - HOUR).astimezone(LOCAL_TZ).hour


def _usable_hours(device: dict[datetime, tuple[float, float]]) -> dict[datetime, float]:
    """Daylight hours the device covered well enough, {hour end: Wh/m^2}."""
    return {
        end: wh
        for end, (wh, covered) in device.items()
        if covered >= MIN_HOUR_COVERAGE * 3600
        and DAYLIGHT_START.hour <= _local_start_hour(end) < DAYLIGHT_END.hour
    }


def compare_hours(
    device: dict[datetime, tuple[float, float]], satellite: dict[datetime, float]
) -> SameDayBenchmark | None:
    """Pair usable device hours with satellite hours; None if nothing matched."""
    matched = [
        (end, wh, satellite[end]) for end, wh in _usable_hours(device).items() if end in satellite
    ]
    if not matched:
        return None

    def ratio(dev: float, sat: float, minimum: float) -> float | None:
        return round(dev / sat, 3) if sat >= minimum else None

    periods = []
    for name, start_h, end_h in PERIODS:
        rows = [(wh, sat) for end, wh, sat in matched if start_h <= _local_start_hour(end) < end_h]
        dev = sum(wh for wh, _ in rows)
        sat = sum(s for _, s in rows)
        periods.append(
            SameDayPeriod(
                period=name,
                start_hour=start_h,
                end_hour=end_h,
                hours=len(rows),
                device_kwh_m2=round(dev / 1000, 3),
                satellite_kwh_m2=round(sat / 1000, 3),
                ratio=ratio(dev, sat, MIN_SATELLITE_WH_PERIOD),
            )
        )

    dev_total = sum(wh for _, wh, _ in matched)
    sat_total = sum(sat for _, _, sat in matched)
    return SameDayBenchmark(
        ratio=ratio(dev_total, sat_total, MIN_SATELLITE_WH_TOTAL),
        days=len({(end - HOUR).astimezone(LOCAL_TZ).date() for end, _, _ in matched}),
        hours=len(matched),
        device_kwh_m2=round(dev_total / 1000, 3),
        satellite_kwh_m2=round(sat_total / 1000, 3),
        periods=periods,
        source=open_meteo.SOURCE,
    )


def _grid(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


async def _satellite_hours(
    db: AsyncSession, lat: float, lng: float, needed: set[datetime]
) -> dict[datetime, float]:
    """Satellite values for `needed` hour ends: from the cache, fetching what's missing."""
    glat, glng = _grid(lat), _grid(lng)
    rows = await db.execute(
        select(SatelliteIrradiance.period_end, SatelliteIrradiance.ghi_wm2).where(
            SatelliteIrradiance.lat == glat,
            SatelliteIrradiance.lng == glng,
            SatelliteIrradiance.period_end >= min(needed),
            SatelliteIrradiance.period_end <= max(needed),
        )
    )
    cached: dict[datetime, float] = dict(rows.tuples().all())

    settled_before = datetime.now(UTC) - SETTLE_TIME
    missing = [end for end in needed if end not in cached and end <= settled_before]
    if not missing:
        return cached

    days: list[date] = sorted({(end - HOUR).astimezone(LOCAL_TZ).date() for end in missing})
    try:
        fetched = await open_meteo.fetch_hourly_ghi(lat, lng, days[0], days[-1])
    except open_meteo.OpenMeteoError as exc:
        # Use whatever is cached; the comparison just covers fewer hours.
        await logger.a_warning("open_meteo_fetch_failed", error=str(exc))
        return cached

    to_store = [
        {"lat": glat, "lng": glng, "period_end": end, "ghi_wm2": ghi}
        for end, ghi in fetched.items()
        if end <= settled_before
    ]
    # Chunked: asyncpg allows at most 32767 bind parameters per statement.
    for i in range(0, len(to_store), 1000):
        stmt = insert(SatelliteIrradiance).values(to_store[i : i + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["lat", "lng", "period_end"],
            set_={"ghi_wm2": stmt.excluded.ghi_wm2, "fetched_at": stmt.excluded.fetched_at},
        )
        await db.execute(stmt)
    if to_store:
        await db.commit()
    return {**cached, **fetched}


async def same_day_comparison(
    db: AsyncSession, lat: float, lng: float, samples: list[Sample]
) -> SameDayBenchmark | None:
    """Device vs same-hour satellite irradiance; None if no hour could be matched."""
    device = hourly_device_energy(samples)
    needed = set(_usable_hours(device))
    if not needed:
        return None
    satellite = await _satellite_hours(db, lat, lng, needed)
    return compare_hours(device, satellite)
