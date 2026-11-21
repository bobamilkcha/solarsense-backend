"""Thin client for Open-Meteo's Satellite Radiation API (Himawari over Asia).

Unlike PVGIS (long-term monthly averages), this gives the irradiance that
actually reached the ground on a given day, so device readings can be compared
with the same weather. No API key; the free tier is for non-commercial use.
Docs: https://open-meteo.com/en/docs/satellite-radiation-api
"""

from datetime import UTC, date, datetime

import httpx

SATELLITE_URL = "https://satellite-api.open-meteo.com/v1/archive"
SOURCE = "Open-Meteo satellite radiation (Himawari)"


class OpenMeteoError(Exception):
    """Raised when Open-Meteo is unreachable or returns an unexpected response shape."""


async def fetch_hourly_ghi(
    lat: float, lng: float, start: date, end: date, *, client: httpx.AsyncClient | None = None
) -> dict[datetime, float]:
    """Hourly mean global horizontal irradiance (W/m^2), `start` to `end` inclusive.

    Keyed by the END of each hour (UTC): Open-Meteo's radiation values are the
    average over the preceding hour, so the 10:00 value covers 09:00-10:00.
    Dates are Malaysian local days. Hours the satellite has no value for yet
    are left out.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        try:
            response = await client.get(
                SATELLITE_URL,
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "hourly": "shortwave_radiation",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "timezone": "Asia/Kuala_Lumpur",
                    "timeformat": "unixtime",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    try:
        hourly = response.json()["hourly"]
        pairs = zip(hourly["time"], hourly["shortwave_radiation"], strict=True)
        return {
            datetime.fromtimestamp(ts, UTC): float(value)
            for ts, value in pairs
            if value is not None
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenMeteoError("Unexpected Open-Meteo response shape") from exc
