"""Integration tests for the readings routes (HTTP layer).

These routes require auth (CurrentUser), so every test authenticates via the
`registered` fixture and sends the access token as a Bearer header.
"""

import uuid
from datetime import UTC, datetime

from app.models import Site
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _auth_headers(registered: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}


async def test_list_sites_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/sites")
    assert resp.status_code == 401


async def test_list_readings_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/readings")
    assert resp.status_code == 401


async def test_list_sites_empty(client: AsyncClient, registered: dict[str, object]) -> None:
    resp = await client.get("/sites", headers=_auth_headers(registered))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_sites_returns_seeded_site(
    client: AsyncClient, db: AsyncSession, registered: dict[str, object]
) -> None:
    site = Site(
        name="Rooftop A",
        device_id="esp32-route-test",
        location_lat=3.1390,
        location_lng=101.6869,
    )
    db.add(site)
    await db.commit()

    resp = await client.get("/sites", headers=_auth_headers(registered))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["device_id"] == "esp32-route-test"


async def test_list_readings_for_unknown_site_404s(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/readings", headers=_auth_headers(registered))
    assert resp.status_code == 404


async def test_list_readings_returns_inserted_reading(
    client: AsyncClient, db: AsyncSession, registered: dict[str, object]
) -> None:
    site = Site(
        name="Rooftop B",
        device_id="esp32-route-test-2",
        location_lat=3.1390,
        location_lng=101.6869,
    )
    db.add(site)
    await db.commit()

    svc = ReadingsService(db)
    await svc.record_reading(
        site.device_id,
        ReadingPayload(
            timestamp=datetime.now(UTC),
            cell_voltage=3.42,
            ambient_temp=31.5,
            humidity=68.2,
            tilt_x=12.3,
            tilt_y=-4.1,
            tilt_z=89.7,
            heading=215.6,
        ),
    )

    resp = await client.get(f"/sites/{site.id}/readings", headers=_auth_headers(registered))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["cell_voltage"] == 3.42
