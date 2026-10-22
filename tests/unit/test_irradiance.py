"""Unit tests for current -> irradiance conversion and daily integration."""

from datetime import UTC, datetime, timedelta

import pytest
from app.modules.benchmark.irradiation import LOCAL_TZ, daily_irradiation
from app.modules.readings.irradiance import irradiance_wm2


def test_full_isc_is_one_sun() -> None:
    assert irradiance_wm2(0.22, isc_stc_a=0.22) == pytest.approx(1000.0)


def test_irradiance_scales_linearly() -> None:
    assert irradiance_wm2(0.05, isc_stc_a=0.2) == pytest.approx(250.0)


def test_negative_noise_clamps_to_zero() -> None:
    assert irradiance_wm2(-0.001, isc_stc_a=0.2) == 0.0


def _series(day: datetime, start_h: int, end_h: int, wm2: float, step_min: int = 10):
    t = day.replace(hour=start_h)
    end = day.replace(hour=end_h)
    out = []
    while t <= end:
        out.append((t, wm2))
        t += timedelta(minutes=step_min)
    return out


def test_constant_sun_over_daylight_window() -> None:
    day = datetime(2026, 3, 15, tzinfo=LOCAL_TZ)
    [result] = daily_irradiation(_series(day, 7, 19, 500.0))

    assert result.kwh_m2 == pytest.approx(6.0)  # 0.5 kW/m^2 * 12 h
    assert result.daylight_coverage == pytest.approx(1.0)
    assert result.is_complete


def test_short_session_is_incomplete() -> None:
    day = datetime(2026, 3, 15, tzinfo=LOCAL_TZ)
    [result] = daily_irradiation(_series(day, 11, 13, 800.0))

    assert result.kwh_m2 == pytest.approx(1.6)
    assert not result.is_complete


def test_large_gaps_are_not_bridged() -> None:
    day = datetime(2026, 3, 15, tzinfo=LOCAL_TZ)
    samples = [(day.replace(hour=9), 800.0), (day.replace(hour=15), 800.0)]
    [result] = daily_irradiation(samples)

    assert result.kwh_m2 == 0.0
    assert result.daylight_coverage == 0.0


def test_days_grouped_in_malaysian_time() -> None:
    # 23:00 UTC on the 14th is 07:00 on the 15th in Malaysia.
    samples = [
        (datetime(2026, 3, 14, 23, 0, tzinfo=UTC), 100.0),
        (datetime(2026, 3, 14, 23, 10, tzinfo=UTC), 100.0),
    ]
    [result] = daily_irradiation(samples)

    assert result.day.isoformat() == "2026-03-15"
