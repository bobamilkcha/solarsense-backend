"""Unit tests for the same-hour device vs satellite comparison (pure functions)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.modules.benchmark.irradiation import LOCAL_TZ
from app.modules.benchmark.open_meteo import OpenMeteoError, fetch_hourly_ghi
from app.modules.benchmark.same_day import compare_hours, hourly_device_energy

DAY = datetime(2026, 11, 20, tzinfo=LOCAL_TZ)


def _series(start: datetime, end: datetime, wm2: float, step_min: int = 1):
    out, t = [], start
    while t <= end:
        out.append((t, wm2))
        t += timedelta(minutes=step_min)
    return out


def _hour_end(h: int) -> datetime:
    """End of local hour starting at h, in UTC (how both sides are keyed)."""
    return (DAY.replace(hour=h) + timedelta(hours=1)).astimezone(UTC)


def test_energy_is_split_at_hour_boundaries() -> None:
    # Two samples 09:30 and 10:30 at a constant 600 W/m^2: half the energy
    # lands in each hour, interpolated at the 10:00 boundary.
    samples = [(DAY.replace(hour=9, minute=30), 600.0), (DAY.replace(hour=10, minute=0), 600.0)]
    samples.append((DAY.replace(hour=10, minute=20), 600.0))
    hours = hourly_device_energy(samples)

    assert hours[_hour_end(9)] == pytest.approx((300.0, 1800.0))
    assert hours[_hour_end(10)] == pytest.approx((200.0, 1200.0))


def test_gaps_over_30_min_are_not_counted() -> None:
    samples = [(DAY.replace(hour=9), 600.0), (DAY.replace(hour=9, minute=45), 600.0)]
    assert hourly_device_energy(samples) == {}


def test_ratio_and_time_of_day_breakdown() -> None:
    # Shaded morning (device 200 vs satellite 600), clear afternoon (both 800).
    samples = _series(DAY.replace(hour=8), DAY.replace(hour=11), 200.0) + _series(
        DAY.replace(hour=14), DAY.replace(hour=16), 800.0
    )
    satellite = {_hour_end(h): 600.0 for h in (8, 9, 10)} | {_hour_end(h): 800.0 for h in (14, 15)}

    result = compare_hours(hourly_device_energy(samples), satellite)

    assert result is not None
    assert result.hours == 5
    assert result.days == 1
    assert result.ratio == pytest.approx((3 * 200 + 2 * 800) / (3 * 600 + 2 * 800), abs=1e-3)
    periods = {p.period: p for p in result.periods}
    assert periods["morning"].ratio == pytest.approx(1 / 3, abs=1e-3)
    assert periods["afternoon"].ratio == pytest.approx(1.0)
    assert periods["midday"].hours == 0
    assert periods["midday"].ratio is None


def test_partly_covered_and_night_hours_are_ignored() -> None:
    # 09:00-09:20 covers only a third of the hour; 21:00 is outside daylight.
    samples = _series(DAY.replace(hour=9), DAY.replace(hour=9, minute=20), 500.0)
    samples += _series(DAY.replace(hour=21), DAY.replace(hour=22), 0.0)
    satellite = {_hour_end(9): 500.0, _hour_end(21): 0.0}

    assert compare_hours(hourly_device_energy(samples), satellite) is None


def test_tiny_satellite_energy_gives_no_ratio() -> None:
    samples = _series(DAY.replace(hour=7), DAY.replace(hour=8), 30.0)
    result = compare_hours(hourly_device_energy(samples), {_hour_end(7): 40.0})

    assert result is not None
    assert result.ratio is None


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_client_keys_by_hour_end_and_drops_nulls() -> None:
    t = int(datetime(2026, 11, 20, 2, 0, tzinfo=UTC).timestamp())  # 10:00 MYT
    payload = {"hourly": {"time": [t, t + 3600], "shortwave_radiation": [512.0, None]}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["start_date"] == "2026-11-20"
        assert request.url.params["timezone"] == "Asia/Kuala_Lumpur"
        return httpx.Response(200, json=payload)

    result = await fetch_hourly_ghi(3.139, 101.687, DAY.date(), DAY.date(), client=_client(handler))

    assert result == {datetime(2026, 11, 20, 2, 0, tzinfo=UTC): 512.0}


async def test_client_errors_raise_open_meteo_error() -> None:
    with pytest.raises(OpenMeteoError):
        await fetch_hourly_ghi(
            3.1, 101.6, DAY.date(), DAY.date(), client=_client(lambda r: httpx.Response(500))
        )
    with pytest.raises(OpenMeteoError):
        await fetch_hourly_ghi(
            3.1,
            101.6,
            DAY.date(),
            DAY.date(),
            client=_client(lambda r: httpx.Response(200, json={})),
        )
