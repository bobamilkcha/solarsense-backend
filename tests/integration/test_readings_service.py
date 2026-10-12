"""Integration tests for ReadingsService (business logic against a real DB)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models import Company, Project, Site
from app.modules.readings.exceptions import SiteNotFoundError, UnknownDeviceError
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_site(db: AsyncSession, **overrides) -> Site:
    """Creates a Company + Project + Site chain, returning the Site.

    `overrides` may include `company_id`/`project_id` to attach the site to an
    already-existing company/project instead of creating new ones.
    """
    company_id = overrides.pop("company_id", None)
    if company_id is None:
        company = Company(name="Test Co")
        db.add(company)
        await db.flush()
        company_id = company.id

    project_id = overrides.pop("project_id", None)
    if project_id is None:
        project = Project(company_id=company_id, name="Test Project")
        db.add(project)
        await db.flush()
        project_id = project.id

    data = {
        "project_id": project_id,
        "name": "Test Site",
        "device_id": "esp32-svc-test",
        "location_lat": 3.1390,
        "location_lng": 101.6869,
    }
    data.update(overrides)
    site = Site(**data)
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


def _payload(**overrides) -> ReadingPayload:
    data = {
        "timestamp": datetime.now(UTC),
        "cell_voltage": 3.42,
        "ambient_temp": 31.5,
        "humidity": 68.2,
        "tilt_x": 12.3,
        "tilt_y": -4.1,
        "tilt_z": 89.7,
        "heading": 215.6,
    }
    data.update(overrides)
    return ReadingPayload(**data)


async def test_record_reading_inserts_row(db: AsyncSession) -> None:
    site = await _make_site(db)

    svc = ReadingsService(db)
    reading = await svc.record_reading(site.device_id, _payload())

    assert reading.id is not None
    assert reading.site_id == site.id
    assert reading.cell_voltage == Decimal("3.42")


async def test_record_reading_derives_current_from_voltage(db: AsyncSession) -> None:
    site = await _make_site(db)

    svc = ReadingsService(db)
    reading = await svc.record_reading(site.device_id, _payload(cell_voltage=5.0))

    assert reading.cell_current == Decimal("0.5")


async def test_record_reading_unknown_device_raises(db: AsyncSession) -> None:
    svc = ReadingsService(db)
    with pytest.raises(UnknownDeviceError):
        await svc.record_reading("no-such-device", _payload())


async def test_list_sites_orders_by_name(db: AsyncSession) -> None:
    company = Company(name="Shared Co")
    db.add(company)
    await db.flush()

    await _make_site(db, company_id=company.id, name="Zeta Site", device_id="esp32-z")
    await _make_site(db, company_id=company.id, name="Alpha Site", device_id="esp32-a")

    svc = ReadingsService(db)
    sites = await svc.list_sites(company.id)

    names = [s.name for s in sites]
    assert names == sorted(names)


async def test_list_sites_super_admin_sees_all_companies(db: AsyncSession) -> None:
    await _make_site(db, name="Co A Site", device_id="esp32-coa")
    await _make_site(db, name="Co B Site", device_id="esp32-cob")

    svc = ReadingsService(db)
    sites = await svc.list_sites(company_id=None)

    assert len(sites) == 2


async def test_list_readings_orders_newest_first(db: AsyncSession) -> None:
    site = await _make_site(db)

    svc = ReadingsService(db)
    older = await svc.record_reading(
        site.device_id, _payload(timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    )
    newer = await svc.record_reading(
        site.device_id, _payload(timestamp=datetime(2026, 6, 1, tzinfo=UTC))
    )

    readings = await svc.list_readings(site.id, company_id=None)

    assert [r.id for r in readings] == [newer.id, older.id]


async def test_list_readings_unknown_site_raises(db: AsyncSession) -> None:
    svc = ReadingsService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.list_readings(uuid.uuid4(), company_id=None)


async def test_list_readings_other_company_raises(db: AsyncSession) -> None:
    site = await _make_site(db)

    svc = ReadingsService(db)
    with pytest.raises(SiteNotFoundError):
        await svc.list_readings(site.id, company_id=uuid.uuid4())
