"""Integration tests for the projects routes (HTTP layer), including RBAC.

Registration always creates a company_admin, so installer-role tests create
that user directly via the ORM and mint an access token for it (quicker than
going through the invitation flow, which test_users_routes.py covers).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.models import SensorReading, Site, User, UserRole
from app.modules.auth import security
from app.modules.bills.service import BILLS_BUCKET
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _auth_headers(registered: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}


async def _installer_headers(db: AsyncSession, company_id: uuid.UUID) -> dict[str, str]:
    user = User(
        company_id=company_id,
        role=UserRole.INSTALLER,
        email="installer@example.com",
        password_hash="unused",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = security.create_access_token(subject=user.id)
    return {"Authorization": f"Bearer {token}"}


async def test_create_project_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/projects", json={"name": "Rooftop Survey"})
    assert resp.status_code == 401


async def test_company_admin_can_create_project(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    resp = await client.post(
        "/projects", json={"name": "Rooftop Survey"}, headers=_auth_headers(registered)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Rooftop Survey"
    assert body["company_id"] == registered["user"]["company_id"]


async def test_installer_cannot_create_project(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    headers = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))
    resp = await client.post("/projects", json={"name": "Rooftop Survey"}, headers=headers)
    assert resp.status_code == 403


async def test_installer_can_list_projects(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    await client.post(
        "/projects", json={"name": "Rooftop Survey"}, headers=_auth_headers(registered)
    )
    headers = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))

    resp = await client.get("/projects", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_company_admin_can_create_site_under_project(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    project_resp = await client.post("/projects", json={"name": "Rooftop Survey"}, headers=headers)
    project_id = project_resp.json()["id"]

    resp = await client.post(
        f"/projects/{project_id}/sites",
        json={
            "name": "Rooftop A",
            "device_id": "esp32-proj-test",
            "location_lat": 3.1390,
            "location_lng": 101.6869,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["device_id"] == "esp32-proj-test"

    sites_resp = await client.get("/sites", headers=headers)
    assert any(s["device_id"] == "esp32-proj-test" for s in sites_resp.json())


async def test_create_site_under_unknown_project_404s(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    resp = await client.post(
        f"/projects/{uuid.uuid4()}/sites",
        json={
            "name": "Rooftop A",
            "device_id": "esp32-proj-test-2",
            "location_lat": 3.1390,
            "location_lng": 101.6869,
        },
        headers=_auth_headers(registered),
    )
    assert resp.status_code == 404


async def test_create_site_duplicate_device_id_conflicts(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    project_resp = await client.post("/projects", json={"name": "Rooftop Survey"}, headers=headers)
    project_id = project_resp.json()["id"]

    site_payload = {
        "name": "Rooftop A",
        "device_id": "esp32-dup-test",
        "location_lat": 3.1390,
        "location_lng": 101.6869,
    }
    first = await client.post(f"/projects/{project_id}/sites", json=site_payload, headers=headers)
    assert first.status_code == 201

    second = await client.post(f"/projects/{project_id}/sites", json=site_payload, headers=headers)
    assert second.status_code == 409


# --- editing and deleting projects and sites ---


async def _project_and_site(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    project = await client.post("/projects", json={"name": "Rooftop Survey"}, headers=headers)
    site = await client.post(
        f"/projects/{project.json()['id']}/sites",
        json={"name": "Rooftop A", "location_lat": 3.1390, "location_lng": 101.6869},
        headers=headers,
    )
    assert site.status_code == 201
    return project.json()["id"], site.json()["id"]


async def _other_company_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/auth/register",
        json={"email": "other@example.com", "password": "Other-pass-123!", "company_name": "Other"},
    )
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def deleted_prefixes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _fake_delete_prefix(bucket: str, prefix: str) -> None:
        calls.append((bucket, prefix))

    monkeypatch.setattr("app.modules.projects.service.delete_prefix", _fake_delete_prefix)
    return calls


async def test_update_project_changes_only_sent_fields(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    created = await client.post(
        "/projects", json={"name": "Old", "description": "Keep me"}, headers=headers
    )
    project_id = created.json()["id"]

    resp = await client.patch(f"/projects/{project_id}", json={"name": "New"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert resp.json()["description"] == "Keep me"

    cleared = await client.patch(
        f"/projects/{project_id}", json={"description": None}, headers=headers
    )
    assert cleared.json()["description"] is None
    assert cleared.json()["name"] == "New"


async def test_update_project_rejects_null_or_empty_name(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    project_id, _ = await _project_and_site(client, headers)
    for body in ({"name": None}, {"name": ""}):
        resp = await client.patch(f"/projects/{project_id}", json=body, headers=headers)
        assert resp.status_code == 422


def _edit_requests(project_id: str, site_id: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("PATCH", f"/projects/{project_id}", {"name": "X"}),
        ("DELETE", f"/projects/{project_id}", None),
        ("PATCH", f"/sites/{site_id}", {"name": "X"}),
        ("DELETE", f"/sites/{site_id}", None),
    ]


async def test_installer_cannot_update_or_delete(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    project_id, site_id = await _project_and_site(client, _auth_headers(registered))
    headers = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))

    for method, url, body in _edit_requests(project_id, site_id):
        resp = await client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 403, (method, url)


async def test_other_company_gets_404(client: AsyncClient, registered: dict[str, Any]) -> None:
    project_id, site_id = await _project_and_site(client, _auth_headers(registered))
    other = await _other_company_headers(client)

    for method, url, body in _edit_requests(project_id, site_id):
        resp = await client.request(method, url, json=body, headers=other)
        assert resp.status_code == 404, (method, url)


async def test_update_site_name_and_location(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    _, site_id = await _project_and_site(client, headers)

    resp = await client.patch(
        f"/sites/{site_id}",
        json={"location_lat": 5.4141, "location_lng": 100.3288},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Rooftop A"
    assert body["location_lat"] == pytest.approx(5.4141)
    assert body["location_lng"] == pytest.approx(100.3288)

    renamed = await client.patch(f"/sites/{site_id}", json={"name": "Rooftop B"}, headers=headers)
    assert renamed.json()["name"] == "Rooftop B"


async def test_update_site_validates_location(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    headers = _auth_headers(registered)
    _, site_id = await _project_and_site(client, headers)
    for body in ({"location_lat": 91}, {"location_lng": None}):
        resp = await client.patch(f"/sites/{site_id}", json=body, headers=headers)
        assert resp.status_code == 422


async def test_delete_site_removes_readings_and_files(
    client: AsyncClient,
    db: AsyncSession,
    registered: dict[str, Any],
    deleted_prefixes: list[tuple[str, str]],
) -> None:
    headers = _auth_headers(registered)
    _, site_id = await _project_and_site(client, headers)
    db.add(
        SensorReading(
            site_id=uuid.UUID(site_id),
            cell_voltage=0.5,
            cell_current=0.05,
            device_timestamp=datetime.now(UTC),
        )
    )
    await db.commit()

    resp = await client.delete(f"/sites/{site_id}", headers=headers)
    assert resp.status_code == 204
    assert await db.get(Site, uuid.UUID(site_id)) is None
    remaining = await db.scalar(
        select(func.count()).where(SensorReading.site_id == uuid.UUID(site_id))
    )
    assert remaining == 0
    assert deleted_prefixes == [(BILLS_BUCKET, site_id)]
    assert (await client.delete(f"/sites/{site_id}", headers=headers)).status_code == 404


async def test_delete_project_removes_its_sites(
    client: AsyncClient,
    db: AsyncSession,
    registered: dict[str, Any],
    deleted_prefixes: list[tuple[str, str]],
) -> None:
    headers = _auth_headers(registered)
    project_id, site_id = await _project_and_site(client, headers)

    resp = await client.delete(f"/projects/{project_id}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get("/projects", headers=headers)).json() == []
    assert await db.get(Site, uuid.UUID(site_id)) is None
    assert deleted_prefixes == [(BILLS_BUCKET, site_id)]
