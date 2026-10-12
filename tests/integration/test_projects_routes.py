"""Integration tests for the projects routes (HTTP layer), including RBAC.

Registration always creates a company_admin (there's no public "join my
company as an installer" endpoint yet), so installer-role tests create that
user directly via the ORM and mint an access token for it.
"""

import uuid
from typing import Any

from app.models import User, UserRole
from app.modules.auth import security
from httpx import AsyncClient
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
