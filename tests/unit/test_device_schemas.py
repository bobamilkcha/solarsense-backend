"""Unit tests for the device picker's short code and signal label."""

import pytest
from app.modules.devices.schemas import short_code, signal_quality


def test_short_code_is_last_four_upper() -> None:
    assert short_code("solarsense-38BB0B71FE68") == "FE68"
    assert short_code("solarsense-38bb0b71fe68") == "FE68"


@pytest.mark.parametrize(
    ("rssi", "expected"),
    [(-50, "good"), (-67, "good"), (-68, "fair"), (-80, "fair"), (-81, "weak"), (None, "unknown")],
)
def test_signal_quality(rssi: int | None, expected: str) -> None:
    assert signal_quality(rssi) == expected
