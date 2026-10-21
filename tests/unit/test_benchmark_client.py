"""Unit tests for the PVGIS client. Uses httpx.MockTransport, no real network call."""

import httpx
import pytest
from app.modules.benchmark.client import PVGISError, fetch_monthly_irradiation_averages


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_averages_across_years_per_month() -> None:
    payload = {
        "outputs": {
            "monthly": [
                {"year": 2020, "month": 1, "H(h)_m": 100.0},
                {"year": 2021, "month": 1, "H(h)_m": 200.0},
                {"year": 2020, "month": 2, "H(h)_m": 50.0},
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = await fetch_monthly_irradiation_averages(3.139, 101.6869, client=_client(handler))

    assert result[1] == pytest.approx(150.0)
    assert result[2] == pytest.approx(50.0)


async def test_http_error_raises_pvgis_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(PVGISError):
        await fetch_monthly_irradiation_averages(3.139, 101.6869, client=_client(handler))


async def test_unexpected_shape_raises_pvgis_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(PVGISError):
        await fetch_monthly_irradiation_averages(3.139, 101.6869, client=_client(handler))
