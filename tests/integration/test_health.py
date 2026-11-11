from httpx import AsyncClient


async def test_health_reports_database_and_mqtt(client: AsyncClient) -> None:
    resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["mqtt"] in (True, False)
