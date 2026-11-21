"""GET /health/readings: alerts when a paired site stops receiving readings."""

from datetime import UTC, datetime, timedelta

from app.core.config.app_config import app_config
from app.models import Device, SensorReading, Site
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_readings_service import _make_site


async def _add_reading(db: AsyncSession, site: Site, age: timedelta) -> None:
    received = datetime.now(UTC) - age
    db.add(
        SensorReading(
            site_id=site.id,
            cell_voltage=3.4,
            cell_current=0.34,
            device_timestamp=received,
            received_at=received,
        )
    )
    await db.commit()


async def test_ok_with_no_paired_sites(client: AsyncClient) -> None:
    resp = await client.get("/health/readings")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "monitored": 0, "stale": 0, "waiting": 0}


async def test_ok_when_readings_are_recent(client: AsyncClient, db: AsyncSession) -> None:
    site = await _make_site(db)
    await _add_reading(db, site, timedelta(minutes=1))

    resp = await client.get("/health/readings")

    assert resp.status_code == 200
    assert resp.json()["monitored"] == 1


async def test_503_when_readings_stop(client: AsyncClient, db: AsyncSession) -> None:
    fresh = await _make_site(db, device_id="esp32-fresh")
    stale = await _make_site(db, device_id="esp32-stale")
    await _add_reading(db, fresh, timedelta(minutes=1))
    await _add_reading(db, stale, timedelta(seconds=app_config.READINGS_STALE_AFTER_S + 60))

    resp = await client.get("/health/readings")

    assert resp.status_code == 503
    assert resp.json() == {"status": "stale", "monitored": 2, "stale": 1, "waiting": 0}


async def test_long_publish_interval_extends_threshold(
    client: AsyncClient, db: AsyncSession
) -> None:
    site = await _make_site(db)
    db.add(Device(id=str(site.device_id), reported_publish_interval_s=3600))
    await db.commit()
    # Older than the default threshold, but within 3x the device's hourly interval.
    await _add_reading(db, site, timedelta(hours=2))

    resp = await client.get("/health/readings")

    assert resp.status_code == 200


async def test_site_without_readings_is_waiting_not_stale(
    client: AsyncClient, db: AsyncSession
) -> None:
    await _make_site(db)
    await _make_site(db, device_id=None, name="Unpaired")

    resp = await client.get("/health/readings")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "monitored": 1, "stale": 0, "waiting": 1}


async def test_accepts_head(client: AsyncClient, db: AsyncSession) -> None:
    # UptimeRobot probes with HEAD: the status code must still reflect staleness.
    assert (await client.head("/health/readings")).status_code == 200

    site = await _make_site(db)
    await _add_reading(db, site, timedelta(seconds=app_config.READINGS_STALE_AFTER_S + 60))

    assert (await client.head("/health/readings")).status_code == 503
