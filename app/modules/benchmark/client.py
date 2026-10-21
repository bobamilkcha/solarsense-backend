"""Thin client for PVGIS (EU Joint Research Centre's free solar radiation API).

No API key required. Docs: https://joint-research-centre.ec.europa.eu/pvgis-online-tool_en
We use the MRcalc ("monthly radiation") tool, which returns one row per
year/month in its historical dataset (2005-2020 for the PVGIS-ERA5 database) —
we average across years ourselves to get a long-term monthly figure.
"""

from collections import defaultdict

import httpx

PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_2/MRcalc"


class PVGISError(Exception):
    """Raised when PVGIS is unreachable or returns an unexpected response shape."""


async def fetch_monthly_irradiation_averages(
    lat: float, lng: float, *, client: httpx.AsyncClient | None = None
) -> dict[int, float]:
    """Long-term average horizontal irradiation per calendar month, in kWh/m2/month.

    Returns a dict keyed 1-12. `client` is injectable for testing; a real
    PVGIS data point is only returned where the site's year range overlaps
    the available historical data for the coordinates.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15.0)

    try:
        try:
            response = await client.get(
                PVGIS_BASE_URL,
                params={"lat": lat, "lon": lng, "horirrad": 1, "outputformat": "json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PVGISError(f"PVGIS request failed: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    try:
        monthly_rows = response.json()["outputs"]["monthly"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PVGISError("Unexpected PVGIS response shape") from exc

    totals: dict[int, list[float]] = defaultdict(list)
    for row in monthly_rows:
        try:
            totals[row["month"]].append(row["H(h)_m"])
        except KeyError as exc:
            raise PVGISError("Unexpected PVGIS response shape") from exc

    return {month: sum(values) / len(values) for month, values in totals.items()}
