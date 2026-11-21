"""GET /sites/{id}/readings/series: bucketed readings for history charts."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import SensorReading, Site
from app.modules.readings.irradiance import irradiance_wm2
from app.modules.readings.service import pick_bucket_s
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_readings_routes import _auth_headers, _own_project

T0 = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)


async def _site(db: AsyncSession, registered: dict[str, Any]) -> Site:
    project = await _own_project(db, registered)
    site = Site(
        project_id=project.id,
        name="Roof",
        device_id="esp32-series",
        location_lat=3.139,
        location_lng=101.6869,
    )
    db.add(site)
    await db.flush()
    return site


def _reading(site: Site, at: datetime, current: float, temp: float | None = 30.0) -> SensorReading:
    return SensorReading(
        site_id=site.id,
        cell_voltage=current * 10,
        cell_current=current,
        ambient_temp=temp,
        humidity=70.0,
        roll=0.0,
        pitch=0.0,
        device_timestamp=at,
    )


def _params(start: datetime, end: datetime, **extra: Any) -> dict[str, Any]:
    return {"start": start.isoformat(), "end": end.isoformat(), **extra}


async def test_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(
        f"/sites/{uuid.uuid4()}/readings/series", params=_params(T0, T0 + timedelta(days=1))
    )
    assert resp.status_code == 401


async def test_buckets_and_summary(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _site(db, registered)
    db.add_all(
        [
            # Bucket 1 (00:00-01:00): two readings.
            _reading(site, T0 + timedelta(minutes=10), 0.02, temp=28.0),
            _reading(site, T0 + timedelta(minutes=40), 0.04, temp=32.0),
            # 01:00 bucket empty, then bucket at 02:00. A negative current is
            # dark-time noise and must count as 0, not drag the average down.
            _reading(site, T0 + timedelta(hours=2, minutes=5), -0.01, temp=None),
            # Outside the range: ignored.
            _reading(site, T0 + timedelta(days=2), 0.5),
        ]
    )
    await db.commit()

    resp = await client.get(
        f"/sites/{site.id}/readings/series",
        params=_params(T0, T0 + timedelta(days=1), bucket_s=3600),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bucket_s"] == 3600
    buckets = body["buckets"]
    assert [b["count"] for b in buckets] == [2, 1]
    assert datetime.fromisoformat(buckets[0]["bucket_start"]) == T0
    assert datetime.fromisoformat(buckets[1]["bucket_start"]) == T0 + timedelta(hours=2)
    assert buckets[0]["irradiance_avg_wm2"] == pytest.approx(irradiance_wm2(0.03), abs=0.1)
    assert buckets[0]["irradiance_max_wm2"] == pytest.approx(irradiance_wm2(0.04), abs=0.1)
    assert buckets[0]["ambient_temp_avg"] == 30.0
    assert buckets[0]["tilt_deg_avg"] == 0.0
    assert buckets[1]["irradiance_avg_wm2"] == 0.0
    assert buckets[1]["ambient_temp_avg"] is None

    summary = body["summary"]
    assert summary["count"] == 3
    assert summary["irradiance_max_wm2"] == pytest.approx(irradiance_wm2(0.04), abs=0.1)
    assert summary["ambient_temp_min"] == 28.0
    assert summary["ambient_temp_max"] == 32.0
    assert datetime.fromisoformat(summary["first_reading_at"]) == T0 + timedelta(minutes=10)


async def test_buckets_align_to_start(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    # Local (UTC+8) midnight as start: daily buckets must begin there, not at UTC midnight.
    site = await _site(db, registered)
    db.add(_reading(site, T0 + timedelta(hours=20), 0.02))  # 04:00 on 16 Nov, MYT
    await db.commit()
    start = T0 + timedelta(hours=16)  # 16 Nov 00:00 MYT

    resp = await client.get(
        f"/sites/{site.id}/readings/series",
        params=_params(start, start + timedelta(days=3), bucket_s=86400),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 200
    assert datetime.fromisoformat(resp.json()["buckets"][0]["bucket_start"]) == start


async def test_empty_range(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _site(db, registered)
    await db.commit()

    resp = await client.get(
        f"/sites/{site.id}/readings/series",
        params=_params(T0, T0 + timedelta(days=7)),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"] == []
    assert body["summary"]["count"] == 0
    assert body["summary"]["irradiance_max_wm2"] is None


async def test_invalid_range_422s(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _site(db, registered)
    await db.commit()

    resp = await client.get(
        f"/sites/{site.id}/readings/series",
        params=_params(T0, T0),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 422


async def test_too_many_buckets_422s(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _site(db, registered)
    await db.commit()

    resp = await client.get(
        f"/sites/{site.id}/readings/series",
        params=_params(T0, T0 + timedelta(days=30), bucket_s=60),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 422


async def test_other_company_site_404s(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.get(
        f"/sites/{uuid.uuid4()}/readings/series",
        params=_params(T0, T0 + timedelta(days=1)),
        headers=_auth_headers(registered),
    )

    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        (timedelta(hours=12), 60),
        (timedelta(days=1), 300),
        (timedelta(days=7), 900),
        (timedelta(days=30), 3600),
        (timedelta(days=365), 43200),
        (timedelta(days=5000), 86400),
    ],
)
def test_pick_bucket_s(span: timedelta, expected: int) -> None:
    assert pick_bucket_s(T0, T0 + span) == expected
