"""Integration tests for the readings routes (HTTP layer).

These routes require auth (CurrentUser) and are scoped to the caller's company,
so every test authenticates via the `registered` fixture and creates sites
under that user's own company so they're visible.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models import Company, Project, Site, User
from app.modules.readings.schemas import ReadingPayload
from app.modules.readings.service import ReadingsService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _auth_headers(registered: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}


async def _own_project(db: AsyncSession, registered: dict[str, Any]) -> Project:
    """A Project under the registered user's own company."""
    user_id = registered["user"]["id"]
    user = await db.get(User, uuid.UUID(user_id))
    assert user is not None
    project = Project(company_id=user.company_id, name="Test Project")
    db.add(project)
    await db.flush()
    return project


async def test_list_sites_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/sites")
    assert resp.status_code == 401


async def test_list_readings_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/readings")
    assert resp.status_code == 401


async def test_list_sites_empty(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.get("/sites", headers=_auth_headers(registered))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_sites_returns_seeded_site(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    project = await _own_project(db, registered)
    site = Site(
        project_id=project.id,
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


async def test_list_sites_excludes_other_companies(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other_company = Company(name="Other Co")
    db.add(other_company)
    await db.flush()
    other_project = Project(company_id=other_company.id, name="Other Project")
    db.add(other_project)
    await db.flush()
    db.add(
        Site(
            project_id=other_project.id,
            name="Other Co Site",
            device_id="esp32-other-co",
            location_lat=3.1390,
            location_lng=101.6869,
        )
    )
    await db.commit()

    resp = await client.get("/sites", headers=_auth_headers(registered))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_readings_for_unknown_site_404s(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    resp = await client.get(f"/sites/{uuid.uuid4()}/readings", headers=_auth_headers(registered))
    assert resp.status_code == 404


async def test_list_readings_returns_inserted_reading(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    project = await _own_project(db, registered)
    site = Site(
        project_id=project.id,
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


async def test_list_readings_for_other_company_site_404s(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other_company = Company(name="Other Co 2")
    db.add(other_company)
    await db.flush()
    other_project = Project(company_id=other_company.id, name="Other Project 2")
    db.add(other_project)
    await db.flush()
    other_site = Site(
        project_id=other_project.id,
        name="Other Co Site 2",
        device_id="esp32-other-co-2",
        location_lat=3.1390,
        location_lng=101.6869,
    )
    db.add(other_site)
    await db.commit()
    await db.refresh(other_site)

    resp = await client.get(f"/sites/{other_site.id}/readings", headers=_auth_headers(registered))
    assert resp.status_code == 404
