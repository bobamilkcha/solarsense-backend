"""Integration tests for device status ingestion and the remote config endpoints."""

from typing import Any

import pytest
from app.main import app
from app.models import Company, Device, Project, Site
from app.modules.devices.deps import get_config_publisher
from app.modules.devices.schemas import StatusPayload
from app.modules.devices.service import DevicesService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_devices_routes import DEVICE, _create_site
from tests.integration.test_projects_routes import _auth_headers, _installer_headers


class FakePublisher:
    def __init__(self, connected: bool = True, accepts: bool = True) -> None:
        self.connected = connected
        self.accepts = accepts
        self.published: list[tuple[str, dict[str, int]]] = []

    def is_connected(self) -> bool:
        return self.connected

    def publish_config(self, device_id: str, config: dict[str, int]) -> bool:
        if self.accepts:
            self.published.append((device_id, config))
        return self.accepts


@pytest.fixture
def publisher() -> FakePublisher:
    fake = FakePublisher()
    app.dependency_overrides[get_config_publisher] = lambda: fake
    return fake


def _online(interval: int = 30, fw: str = "0.3.0") -> StatusPayload:
    return StatusPayload(online=True, fw=fw, publish_interval_s=interval)


async def _paired_device(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> dict[str, str]:
    headers = _auth_headers(registered)
    await DevicesService(db).apply_status(DEVICE, _online())
    await _create_site(client, headers, device_id=DEVICE)
    return headers


async def test_status_online_then_will_keeps_fw_and_interval(db: AsyncSession) -> None:
    svc = DevicesService(db)
    await svc.apply_status(DEVICE, _online(interval=60, fw="0.3.0"))
    await svc.apply_status(DEVICE, StatusPayload(online=False))

    device = await db.get(Device, DEVICE)
    assert device is not None
    await db.refresh(device)
    assert device.online is False
    assert device.fw == "0.3.0"
    assert device.reported_publish_interval_s == 60


async def test_retained_status_does_not_refresh_last_seen(db: AsyncSession) -> None:
    svc = DevicesService(db)
    await svc.apply_status(DEVICE, _online())
    device = await db.get(Device, DEVICE)
    assert device is not None
    await db.refresh(device)
    first_seen = device.last_seen_at

    await svc.apply_status(DEVICE, _online(interval=45), retained=True)
    await db.refresh(device)

    assert device.reported_publish_interval_s == 45
    assert device.last_seen_at == first_seen


async def test_get_config_before_any_request_is_synced(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = await _paired_device(client, db, registered)

    resp = await client.get(f"/devices/{DEVICE}/config", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["desired"] == {"publish_interval_s": None, "requested_at": None}
    assert body["reported"]["online"] is True
    assert body["reported"]["fw"] == "0.3.0"
    assert body["reported"]["publish_interval_s"] == 30
    assert body["synced"] is True


async def test_put_config_publishes_and_is_pending_until_device_confirms(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    headers = await _paired_device(client, db, registered)

    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": 120}, headers=headers
    )

    assert resp.status_code == 200
    assert publisher.published == [(DEVICE, {"publish_interval_s": 120})]
    body = resp.json()
    assert body["desired"]["publish_interval_s"] == 120
    assert body["desired"]["requested_at"] is not None
    assert body["reported"]["publish_interval_s"] == 30
    assert body["synced"] is False

    await DevicesService(db).apply_status(DEVICE, _online(interval=120))
    resp = await client.get(f"/devices/{DEVICE}/config", headers=headers)
    assert resp.json()["synced"] is True


@pytest.mark.parametrize("value", [4, 3601, 0, "30", 12.5])
async def test_put_config_rejects_bad_interval(
    client: AsyncClient,
    db: AsyncSession,
    registered: dict[str, Any],
    publisher: FakePublisher,
    value: object,
) -> None:
    headers = await _paired_device(client, db, registered)

    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": value}, headers=headers
    )

    assert resp.status_code == 422
    assert publisher.published == []


async def test_put_config_broker_down_saves_nothing(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    headers = await _paired_device(client, db, registered)
    publisher.connected = False

    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": 60}, headers=headers
    )

    assert resp.status_code == 503
    got = await client.get(f"/devices/{DEVICE}/config", headers=headers)
    assert got.json()["desired"]["publish_interval_s"] is None


async def test_put_config_publish_rejected_rolls_back(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    headers = await _paired_device(client, db, registered)
    publisher.accepts = False

    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": 60}, headers=headers
    )

    assert resp.status_code == 503
    got = await client.get(f"/devices/{DEVICE}/config", headers=headers)
    assert got.json()["desired"]["publish_interval_s"] is None


async def test_unpaired_device_config_404(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    await DevicesService(db).apply_status(DEVICE, _online())
    headers = _auth_headers(registered)

    assert (await client.get(f"/devices/{DEVICE}/config", headers=headers)).status_code == 404
    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": 60}, headers=headers
    )
    assert resp.status_code == 404
    assert publisher.published == []


async def test_other_company_device_config_404(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    other = Company(name="Other Co")
    db.add(other)
    await db.flush()
    project = Project(company_id=other.id, name="Other Project")
    db.add(project)
    await db.flush()
    db.add(
        Site(
            project_id=project.id,
            name="Other Site",
            device_id="solarsense-AAAAAAAAAAAA",
            location_lat=3.139,
            location_lng=101.6869,
        )
    )
    await DevicesService(db).apply_status("solarsense-AAAAAAAAAAAA", _online())
    headers = _auth_headers(registered)

    url = "/devices/solarsense-AAAAAAAAAAAA/config"
    assert (await client.get(url, headers=headers)).status_code == 404
    resp = await client.put(url, json={"publish_interval_s": 60}, headers=headers)
    assert resp.status_code == 404
    assert publisher.published == []


async def test_installer_cannot_use_config_endpoints(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any], publisher: FakePublisher
) -> None:
    await _paired_device(client, db, registered)
    import uuid

    headers = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))

    assert (await client.get(f"/devices/{DEVICE}/config", headers=headers)).status_code == 403
    resp = await client.put(
        f"/devices/{DEVICE}/config", json={"publish_interval_s": 60}, headers=headers
    )
    assert resp.status_code == 403
