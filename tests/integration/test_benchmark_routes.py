"""Integration tests for the benchmark route (HTTP layer), PVGIS mocked out."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.models import Project, Site, User
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _auth_headers(registered: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}


async def _own_site(db: AsyncSession, registered: dict[str, Any]) -> Site:
    user = await db.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None
    project = Project(company_id=user.company_id, name="Test Project")
    db.add(project)
    await db.flush()
    site = Site(
        project_id=project.id,
        name="Rooftop A",
        device_id="esp32-benchmark-test",
        location_lat=3.1390,
        location_lng=101.6869,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


async def test_benchmark_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/benchmark")
    assert resp.status_code == 401


async def test_benchmark_unknown_site_404s(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/benchmark", headers=_auth_headers(registered))
    assert resp.status_code == 404


async def test_benchmark_returns_comparison(
    client: AsyncClient,
    db: AsyncSession,
    registered: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = await _own_site(db, registered)
    readings_svc = ReadingsService(db)
    await readings_svc.record_reading(
        site.device_id,
        ReadingPayload(
            timestamp=datetime(2026, 7, 10, tzinfo=UTC),
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
        return {7: 180.0}

    monkeypatch.setattr(
        "app.modules.benchmark.service.fetch_monthly_irradiation_averages", fake_fetch
    )

    resp = await client.get(
        f"/sites/{site.id}/benchmark?month=7", headers=_auth_headers(registered)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == 7
    assert body["device_reading_count"] == 1
    assert body["satellite_avg_monthly_irradiation_kwh_m2"] == 180.0
