"""Integration tests for device discovery and pairing."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import Company, Device, Project, Site
from app.modules.devices.service import DevicesService
from app.modules.readings.service import ReadingsService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_projects_routes import _auth_headers, _installer_headers
from tests.integration.test_readings_service import _payload

DEVICE = "solarsense-38BB0B71FE68"


async def _create_site(
    client: AsyncClient, headers: dict[str, str], device_id: str | None = None
) -> dict[str, Any]:
    project = await client.post("/projects", json={"name": "Rooftop"}, headers=headers)
    body: dict[str, Any] = {"name": "Roof A", "location_lat": 3.139, "location_lng": 101.6869}
    if device_id is not None:
        body["device_id"] = device_id
    resp = await client.post(f"/projects/{project.json()['id']}/sites", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _unpaired_ids(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    resp = await client.get("/devices/unpaired", headers=headers)
    assert resp.status_code == 200
    return [d["device_id"] for d in resp.json()]


async def test_mark_seen_records_and_updates_device(db: AsyncSession) -> None:
    svc = DevicesService(db)
    await svc.mark_seen(DEVICE, -59)
    await svc.mark_seen(DEVICE, -72)

    device = await db.get(Device, DEVICE)
    assert device is not None
    await db.refresh(device)
    assert device.last_rssi == -72


async def test_unpaired_lists_online_devices_with_short_code(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    await DevicesService(db).mark_seen(DEVICE, -59)

    resp = await client.get("/devices/unpaired", headers=_auth_headers(registered))

    assert resp.status_code == 200
    [device] = resp.json()
    assert device["device_id"] == DEVICE
    assert device["short_code"] == "FE68"
    assert device["last_rssi"] == -59
    assert device["signal"] == "good"


async def test_unpaired_hides_stale_and_paired_devices(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    db.add(Device(id="solarsense-OLD000000001", last_seen_at=two_hours_ago))
    await db.commit()
    await DevicesService(db).mark_seen(DEVICE, -59)
    await DevicesService(db).mark_seen("solarsense-PAIRED000001", -59)
    await _create_site(client, headers, device_id="solarsense-PAIRED000001")

    assert await _unpaired_ids(client, headers) == [DEVICE]


async def test_installer_cannot_list_or_pair(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _create_site(client, _auth_headers(registered))
    headers = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))

    assert (await client.get("/devices/unpaired", headers=headers)).status_code == 403
    resp = await client.put(
        f"/sites/{site['id']}/device", json={"device_id": DEVICE}, headers=headers
    )
    assert resp.status_code == 403


async def test_create_site_without_device_then_pair(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    await DevicesService(db).mark_seen(DEVICE, -59)
    site = await _create_site(client, headers)
    assert site["device_id"] is None

    resp = await client.put(
        f"/sites/{site['id']}/device", json={"device_id": DEVICE}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["device_id"] == DEVICE
    assert await _unpaired_ids(client, headers) == []


async def test_pair_device_already_on_another_site_conflicts(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    await _create_site(client, headers, device_id=DEVICE)
    other = await _create_site(client, headers)

    resp = await client.put(
        f"/sites/{other['id']}/device", json={"device_id": DEVICE}, headers=headers
    )

    assert resp.status_code == 409


async def test_pair_same_device_again_is_noop(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    site = await _create_site(client, headers, device_id=DEVICE)

    resp = await client.put(
        f"/sites/{site['id']}/device", json={"device_id": DEVICE}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["device_id"] == DEVICE


async def test_pair_replaces_sites_previous_device(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    await DevicesService(db).mark_seen(DEVICE, -59)
    site = await _create_site(client, headers, device_id=DEVICE)

    resp = await client.put(
        f"/sites/{site['id']}/device",
        json={"device_id": "solarsense-AAAAAAAA0002"},
        headers=headers,
    )

    assert resp.json()["device_id"] == "solarsense-AAAAAAAA0002"
    assert await _unpaired_ids(client, headers) == [DEVICE]


async def test_unpair_keeps_readings_and_frees_device(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    site = await _create_site(client, headers, device_id=DEVICE)
    await DevicesService(db).mark_seen(DEVICE, -59)
    await ReadingsService(db).record_reading(DEVICE, _payload())

    resp = await client.delete(f"/sites/{site['id']}/device", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["device_id"] is None
    assert await _unpaired_ids(client, headers) == [DEVICE]
    readings = await client.get(f"/sites/{site['id']}/readings", headers=headers)
    assert len(readings.json()) == 1


async def test_cannot_pair_other_companys_site(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    company = Company(name="Other Co")
    db.add(company)
    await db.flush()
    project = Project(company_id=company.id, name="Theirs")
    db.add(project)
    await db.flush()
    site = Site(project_id=project.id, name="Their Roof", location_lat=3.0, location_lng=101.0)
    db.add(site)
    await db.commit()

    headers = _auth_headers(registered)
    put = await client.put(f"/sites/{site.id}/device", json={"device_id": DEVICE}, headers=headers)
    delete = await client.delete(f"/sites/{site.id}/device", headers=headers)

    assert put.status_code == 404
    assert delete.status_code == 404
