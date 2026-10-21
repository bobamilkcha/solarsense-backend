"""Integration tests for BenchmarkService (DB side), with PVGIS mocked out."""

import uuid
from datetime import UTC, datetime

import pytest
from app.modules.benchmark.client import PVGISError
from app.modules.benchmark.exceptions import BenchmarkUnavailableError
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
