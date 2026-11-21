"""Same-hour satellite comparison: caching, fallbacks, and use in benchmark/report."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from app.core.config.app_config import app_config
from app.models import SatelliteIrradiance, Site
from app.modules.benchmark.irradiation import LOCAL_TZ
from app.modules.benchmark.open_meteo import OpenMeteoError
from app.modules.benchmark.same_day import same_day_comparison
from app.modules.benchmark.service import BenchmarkService
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_readings_service import _make_site
from tests.integration.test_reports_routes import FLAT_IRR, _add_bill, _auth_headers, _own_site

DAY = datetime(2026, 3, 15, tzinfo=LOCAL_TZ)
FETCH = "app.modules.benchmark.open_meteo.fetch_hourly_ghi"


@pytest.fixture
def fake_pvgis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch(lat, lng, *, client=None):
        return FLAT_IRR

    monkeypatch.setattr("app.modules.reports.service.fetch_monthly_irradiation_averages", fetch)


async def _record_day(db: AsyncSession, site: Site, cell_voltage: float) -> None:
    """Readings every 10 min, 07:00-19:00 on DAY, all at the same voltage."""
    readings = ReadingsService(db)
    t = DAY.replace(hour=7)
    while t <= DAY.replace(hour=19):
        await readings.record_reading(
            str(site.device_id),
            ReadingPayload(timestamp=t, cell_voltage=cell_voltage, roll=0, pitch=0),
        )
        t += timedelta(minutes=10)


def _samples(wm2: float) -> list[tuple[datetime, float]]:
    out, t = [], DAY.replace(hour=7)
    while t <= DAY.replace(hour=19):
        out.append((t, wm2))
        t += timedelta(minutes=5)
    return out


def _fake_satellite(wm2: float, calls: list[tuple[date, date]]):
    async def fetch(lat, lng, start, end, *, client=None):
        calls.append((start, end))
        hours = {}
        t = datetime.combine(start, datetime.min.time(), LOCAL_TZ)
        while t.date() <= end:
            hours[(t + timedelta(hours=1)).astimezone(UTC)] = wm2 if 7 <= t.hour < 19 else 0.0
            t += timedelta(hours=1)
        return hours

    return fetch


async def test_compares_and_caches(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[date, date]] = []
    monkeypatch.setattr(FETCH, _fake_satellite(800.0, calls))

    first = await same_day_comparison(db, 3.1391, 101.6869, _samples(400.0))
    second = await same_day_comparison(db, 3.1391, 101.6869, _samples(400.0))

    assert first is not None
    assert first.ratio == pytest.approx(0.5)
    assert first.hours == 12
    assert first.days == 1
    assert second == first
    assert calls == [(DAY.date(), DAY.date())]  # second call served from the cache
    stored = await db.scalar(select(func.count()).select_from(SatelliteIrradiance))
    assert stored == 24


async def test_unreachable_satellite_gives_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: Any, **kwargs: Any):
        raise OpenMeteoError("down")

    monkeypatch.setattr(FETCH, fail)

    assert await same_day_comparison(db, 3.14, 101.69, _samples(400.0)) is None


async def test_benchmark_includes_same_day(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_config, "ISC_STC_MA", 200.0)
    monkeypatch.setattr(FETCH, _fake_satellite(400.0, []))

    async def pvgis(lat, lng, *, client=None):
        return {3: 150.0}

    monkeypatch.setattr("app.modules.benchmark.service.fetch_monthly_irradiation_averages", pvgis)
    site = await _make_site(db)
    await _record_day(db, site, cell_voltage=0.4)  # 200 W/m^2 all day

    result = await BenchmarkService(db).compare(site.id, company_id=None, month=3)

    assert result.same_day is not None
    assert result.same_day.ratio == pytest.approx(0.5)
    assert [p.ratio for p in result.same_day.periods] == pytest.approx([0.5, 0.5, 0.5])


async def test_report_prefers_same_day_shading(
    client: AsyncClient,
    db: AsyncSession,
    registered: dict[str, Any],
    fake_pvgis: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_config, "ISC_STC_MA", 200.0)
    monkeypatch.setattr(FETCH, _fake_satellite(250.0, []))
    site = await _own_site(db, registered)
    await _add_bill(db, site.id)
    await _record_day(db, site, cell_voltage=0.4)  # 200 W/m^2 vs satellite 250

    resp = await client.get(
        f"/sites/{site.id}/feasibility",
        params={"system_kwp": 5},
        headers=_auth_headers(registered),
    )
    body = resp.json()

    assert resp.status_code == 200, resp.text
    assert body["shading"]["source"] == "device_same_day"
    assert body["shading"]["complete_days"] == 1
    assert body["shading"]["applied_factor"] == pytest.approx(0.8, abs=1e-3)
