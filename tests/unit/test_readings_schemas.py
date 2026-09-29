"""Unit tests for ReadingPayload validation (the MQTT invalid-payload path)."""

import pytest
from app.modules.readings.schemas import ReadingPayload
from pydantic import ValidationError


def _payload(**overrides) -> dict:
    data = {
        "timestamp": "2026-01-01T00:00:00Z",
        "cell_voltage": 3.42,
        "ambient_temp": 31.5,
        "humidity": 68.2,
        "tilt_x": 12.3,
        "tilt_y": -4.1,
        "tilt_z": 89.7,
        "heading": 215.6,
    }
    data.update(overrides)
    return data


def test_valid_payload_parses() -> None:
    ReadingPayload(**_payload())


def test_missing_field_rejected() -> None:
    payload = _payload()
    del payload["cell_voltage"]
    with pytest.raises(ValidationError):
        ReadingPayload(**payload)


def test_non_numeric_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ReadingPayload(**_payload(cell_voltage="not-a-number"))


def test_missing_timestamp_rejected() -> None:
    payload = _payload()
    del payload["timestamp"]
    with pytest.raises(ValidationError):
        ReadingPayload(**payload)
