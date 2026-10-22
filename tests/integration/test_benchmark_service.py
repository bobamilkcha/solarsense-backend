"""Integration tests for BenchmarkService (DB side), with PVGIS mocked out."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config.app_config import app_config
from app.modules.benchmark.client import PVGISError
from app.modules.benchmark.exceptions import BenchmarkUnavailableError
from app.modules.benchmark.irradiation import LOCAL_TZ
from app.modules.benchmark.service import BenchmarkService
from app.modules.readings.exceptions import SiteNotFoundError
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_readings_service import _make_site


async def test_compare_combines_device_and_satellite_data(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = await _make_site(db)
    readings_svc = ReadingsService(db)
    await readings_svc.record_reading(
        site.device_id,
        ReadingPayload(
            timestamp=datetime(2026, 3, 15, tzinfo=UTC),
            cell_voltage=3.42,
            ambient_temp=31.5,
            humidity=68.2,
            tilt_x=12.3,
            tilt_y=-4.1,
            tilt_z=89.7,
            heading=215.6,
        ),
    )

    async def fake_fetch(lat, lng, *, client=None):
        return {3: 160.5}

    monkeypatch.setattr(
        "app.modules.benchmark.service.fetch_monthly_irradiation_averages", fake_fetch
    )

    svc = BenchmarkService(db)
    result = await svc.compare(site.id, company_id=None, month=3)

    assert result.month == 3
    assert result.device_reading_count == 1
    assert result.device_avg_cell_voltage == pytest.approx(3.42)
    assert result.satellite_avg_monthly_irradiation_kwh_m2 == pytest.approx(160.5)
    assert result.satellite_source == "PVGIS-ERA5"


def _payload(ts: datetime, cell_voltage: float) -> ReadingPayload:
    return ReadingPayload(
        timestamp=ts,
        cell_voltage=cell_voltage,
        ambient_temp=31.5,
        humidity=68.2,
        tilt_x=0.0,
        tilt_y=0.0,
        tilt_z=90.0,
        heading=180.0,
    )


async def test_compare_converts_device_readings_to_daily_irradiation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_config, "REFERENCE_CELL_ISC_A", 0.2)
    site = await _make_site(db)
    readings_svc = ReadingsService(db)

    # Complete day: 07:00-19:00 local every 10 min at 1.0 V across the 10 ohm
    # shunt -> 0.1 A -> 500 W/m^2 -> 6 kWh/m^2 for the day.
    t = datetime(2026, 3, 15, 7, 0, tzinfo=LOCAL_TZ)
    while t <= datetime(2026, 3, 15, 19, 0, tzinfo=LOCAL_TZ):
        await readings_svc.record_reading(site.device_id, _payload(t, 1.0))
        t += timedelta(minutes=10)
    # Incomplete day: a short midday session, excluded from the daily average.
    for minute in (0, 10, 20):
        ts = datetime(2026, 3, 16, 12, minute, tzinfo=LOCAL_TZ)
        await readings_svc.record_reading(site.device_id, _payload(ts, 2.0))

    async def fake_fetch(lat, lng, *, client=None):
        return {3: 155.0}  # 5 kWh/m^2/day over 31 days

    monkeypatch.setattr(
        "app.modules.benchmark.service.fetch_monthly_irradiation_averages", fake_fetch
    )

    result = await BenchmarkService(db).compare(site.id, company_id=None, month=3)

    assert result.device_reading_count == 76
    assert result.device_complete_days == 1
    assert result.device_avg_daily_irradiation_kwh_m2 == pytest.approx(6.0)
    assert result.satellite_avg_daily_irradiation_kwh_m2 == pytest.approx(5.0)
    assert result.device_to_satellite_ratio == pytest.approx(1.2)
    assert result.reference_cell_isc_a == 0.2


async def test_compare_unknown_site_raises(db: AsyncSession) -> None:
    svc = BenchmarkService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.compare(uuid.uuid4(), company_id=None, month=1)


async def test_compare_other_company_raises(db: AsyncSession) -> None:
    site = await _make_site(db)

    svc = BenchmarkService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.compare(site.id, company_id=uuid.uuid4(), month=1)


async def test_compare_no_readings_returns_none_averages(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = await _make_site(db)

    async def fake_fetch(lat, lng, *, client=None):
        return {5: 170.0}

    monkeypatch.setattr(
        "app.modules.benchmark.service.fetch_monthly_irradiation_averages", fake_fetch
    )

    svc = BenchmarkService(db)
    result = await svc.compare(site.id, company_id=None, month=5)

    assert result.device_reading_count == 0
    assert result.device_avg_cell_voltage is None
    assert result.device_avg_irradiance_wm2 is None
    assert result.device_complete_days == 0
    assert result.device_to_satellite_ratio is None
    assert result.satellite_avg_monthly_irradiation_kwh_m2 == pytest.approx(170.0)


async def test_compare_pvgis_failure_raises_benchmark_unavailable(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = await _make_site(db)

    async def fake_fetch(lat, lng, *, client=None):
        raise PVGISError("boom")

    monkeypatch.setattr(
        "app.modules.benchmark.service.fetch_monthly_irradiation_averages", fake_fetch
    )

    svc = BenchmarkService(db)
    with pytest.raises(BenchmarkUnavailableError):
        await svc.compare(site.id, company_id=None, month=1)
