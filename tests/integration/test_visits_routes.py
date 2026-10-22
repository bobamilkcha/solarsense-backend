"""Integration tests for site visits and their checklists (FR6)."""

import uuid
from typing import Any

from app.models import Project
from app.modules.visits.template import default_items
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_bills_routes import _auth_headers, _own_site
from tests.integration.test_projects_routes import _installer_headers
from tests.integration.test_readings_service import _make_site


async def _create_visit(
    client: AsyncClient, site_id: uuid.UUID, headers: dict[str, str], **body: Any
) -> dict[str, Any]:
    resp = await client.post(f"/sites/{site_id}/visits", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _mark_all(
    client: AsyncClient, visit: dict[str, Any], headers: dict[str, str], status: str = "ok"
) -> None:
    for item in visit["items"]:
        resp = await client.patch(
            f"/visits/{visit['id']}/items/{item['id']}", json={"status": status}, headers=headers
        )
        assert resp.status_code == 200


async def test_create_visit_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(f"/sites/{uuid.uuid4()}/visits", json={})
    assert resp.status_code == 401


async def test_create_visit_with_default_checklist(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    visit = await _create_visit(client, site.id, _auth_headers(registered), notes="Sunny day")

    assert visit["status"] == "in_progress"
    assert visit["notes"] == "Sunny day"
    assert visit["visited_by_id"] == registered["user"]["id"]
    assert len(visit["items"]) == len(default_items())
    assert visit["items"][0]["category"] == "Roof"
    assert [i["position"] for i in visit["items"]] == list(range(len(default_items())))
    assert visit["progress"]["pending"] == len(default_items())


async def test_create_empty_visit(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    visit = await _create_visit(
        client, site.id, _auth_headers(registered), use_default_checklist=False
    )
    assert visit["items"] == []


async def test_installer_can_run_a_visit(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    installer = await _installer_headers(db, uuid.UUID(registered["user"]["company_id"]))

    visit = await _create_visit(client, site.id, installer)
    item = visit["items"][3]  # usable roof area
    resp = await client.patch(
        f"/visits/{visit['id']}/items/{item['id']}",
        json={"status": "ok", "value": "45 m²", "notes": "South-facing slope"},
        headers=installer,
    )

    assert resp.status_code == 200
    assert resp.json()["value"] == "45 m²"
    assert resp.json()["status"] == "ok"


async def test_other_company_cannot_see_visits(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other_site = await _make_site(db)
    headers = _auth_headers(registered)

    assert (
        await client.post(f"/sites/{other_site.id}/visits", json={}, headers=headers)
    ).status_code == 404
    assert (await client.get(f"/sites/{other_site.id}/visits", headers=headers)).status_code == 404


async def test_other_company_visit_404s(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    other_site = await _make_site(db)
    other_admin = await _installer_headers(db, (await _project_company(db, other_site)))
    visit = await _create_visit(client, other_site.id, other_admin)

    resp = await client.get(f"/visits/{visit['id']}", headers=_auth_headers(registered))
    assert resp.status_code == 404


async def _project_company(db: AsyncSession, site: Any) -> uuid.UUID:
    project = await db.get(Project, site.project_id)
    assert project is not None
    return project.company_id


async def test_list_visits_newest_first_with_progress(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    older = await _create_visit(client, site.id, headers, visited_at="2026-09-01T09:00:00+08:00")
    newer = await _create_visit(client, site.id, headers, visited_at="2026-10-01T09:00:00+08:00")
    first_item = newer["items"][0]["id"]
    await client.patch(
        f"/visits/{newer['id']}/items/{first_item}", json={"status": "issue"}, headers=headers
    )

    resp = await client.get(f"/sites/{site.id}/visits", headers=headers)
    body = resp.json()

    assert [v["id"] for v in body] == [newer["id"], older["id"]]
    assert "items" not in body[0]
    assert body[0]["progress"]["issue"] == 1


async def test_add_and_delete_custom_item(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    visit = await _create_visit(client, site.id, headers)

    added = await client.post(
        f"/visits/{visit['id']}/items",
        json={"category": "Roof", "label": "Skylight positions"},
        headers=headers,
    )
    assert added.status_code == 201
    assert added.json()["position"] == len(default_items())

    deleted = await client.delete(
        f"/visits/{visit['id']}/items/{added.json()['id']}", headers=headers
    )
    assert deleted.status_code == 204
    again = await client.delete(
        f"/visits/{visit['id']}/items/{added.json()['id']}", headers=headers
    )
    assert again.status_code == 404


async def test_cannot_complete_with_pending_items(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    visit = await _create_visit(client, site.id, headers)

    resp = await client.patch(
        f"/visits/{visit['id']}", json={"status": "completed"}, headers=headers
    )
    assert resp.status_code == 409


async def test_complete_locks_visit_until_reopened(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    visit = await _create_visit(client, site.id, headers)
    await _mark_all(client, visit, headers, status="not_applicable")

    done = await client.patch(
        f"/visits/{visit['id']}", json={"status": "completed"}, headers=headers
    )
    assert done.status_code == 200
    assert done.json()["status"] == "completed"
    assert done.json()["completed_at"] is not None

    item_id = visit["items"][0]["id"]
    locked_item = await client.patch(
        f"/visits/{visit['id']}/items/{item_id}", json={"status": "issue"}, headers=headers
    )
    assert locked_item.status_code == 409
    locked_notes = await client.patch(
        f"/visits/{visit['id']}", json={"notes": "late edit"}, headers=headers
    )
    assert locked_notes.status_code == 409

    reopened = await client.patch(
        f"/visits/{visit['id']}", json={"status": "in_progress"}, headers=headers
    )
    assert reopened.status_code == 200
    assert reopened.json()["completed_at"] is None
    edit = await client.patch(
        f"/visits/{visit['id']}/items/{item_id}", json={"status": "issue"}, headers=headers
    )
    assert edit.status_code == 200


async def test_null_required_fields_are_ignored(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    visit = await _create_visit(client, site.id, headers)
    item = visit["items"][0]

    resp = await client.patch(
        f"/visits/{visit['id']}/items/{item['id']}",
        json={"label": None, "status": None, "value": "metal deck"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == item["label"]
    assert resp.json()["status"] == "pending"
    assert resp.json()["value"] == "metal deck"


async def test_delete_visit(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)
    visit = await _create_visit(client, site.id, headers)

    assert (await client.delete(f"/visits/{visit['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"/visits/{visit['id']}", headers=headers)).status_code == 404
