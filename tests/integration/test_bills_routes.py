"""Integration tests for the bills routes (HTTP layer), object storage faked out."""

import uuid
from typing import Any

import pytest
from app.models import Project, Site, User
from app.modules.bills.parser import ParsedBillFields
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _auth_headers(registered: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['access_token']}"}


async def _own_site(db: AsyncSession, registered: dict[str, Any]) -> Site:
    user = await db.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None
    project = Project(company_id=user.company_id, name="Bill Test Project")
    db.add(project)
    await db.flush()
    site = Site(
        project_id=project.id,
        name="Bill Test Site",
        device_id="esp32-bill-route-test",
        location_lat=3.1390,
        location_lng=101.6869,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


@pytest.fixture(autouse=True)
def fake_storage_and_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    objects: dict[tuple[str, str], bytes] = {}

    async def ensure_bucket(bucket: str) -> None:
        pass

    async def upload_bytes(bucket: str, object_name: str, data: bytes, content_type: str) -> None:
        objects[(bucket, object_name)] = data

    async def get_bytes(bucket: str, object_name: str) -> bytes:
        return objects[(bucket, object_name)]

    monkeypatch.setattr("app.modules.bills.service.ensure_bucket", ensure_bucket)
    monkeypatch.setattr("app.modules.bills.service.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.modules.bills.service.get_bytes", get_bytes)
    monkeypatch.setattr(
        "app.modules.bills.service.parse_bill_pdf",
        lambda pdf_bytes: ParsedBillFields(kwh_used=100.0, amount_due=50.0),
    )


async def test_upload_bill_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        f"/sites/{uuid.uuid4()}/bills", files={"file": ("bill.pdf", b"x", "application/pdf")}
    )
    assert resp.status_code == 401


async def test_upload_and_list_and_download_bill(
    client: AsyncClient, db: AsyncSession, registered: dict[str, Any]
) -> None:
    site = await _own_site(db, registered)
    headers = _auth_headers(registered)

    upload_resp = await client.post(
        f"/sites/{site.id}/bills",
        files={"file": ("sep2026.pdf", b"original-pdf-bytes", "application/pdf")},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    body = upload_resp.json()
    assert body["filename"] == "sep2026.pdf"
    assert body["kwh_used"] == 100.0

    list_resp = await client.get(f"/sites/{site.id}/bills", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    download_resp = await client.get(f"/bills/{body['id']}/file", headers=headers)
    assert download_resp.status_code == 200
    assert download_resp.content == b"original-pdf-bytes"


async def test_upload_bill_for_unknown_site_404s(
    client: AsyncClient, registered: dict[str, Any]
) -> None:
    resp = await client.post(
        f"/sites/{uuid.uuid4()}/bills",
        files={"file": ("x.pdf", b"x", "application/pdf")},
        headers=_auth_headers(registered),
    )
    assert resp.status_code == 404


async def test_download_unknown_bill_404s(client: AsyncClient, registered: dict[str, Any]) -> None:
    resp = await client.get(f"/bills/{uuid.uuid4()}/file", headers=_auth_headers(registered))
    assert resp.status_code == 404
