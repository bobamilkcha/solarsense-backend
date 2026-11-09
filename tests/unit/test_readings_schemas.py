"""Unit tests for ReadingPayload validation (the MQTT invalid-payload path)."""

import uuid
from datetime import UTC, datetime

import pytest
from app.modules.readings.schemas import ReadingPayload, SensorReadingResponse
from pydantic import ValidationError


def _payload(**overrides) -> dict:
    data = {
        "timestamp": "2026-01-01T00:00:00Z",
        "cell_voltage": 3.42,
        "ambient_temp": 31.5,
        "humidity": 68.2,
        "pitch": 12.3,
        "roll": -4.1,
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


# Captured from a real device (solarsense-38BB0B71FE68).
DEVICE_PAYLOAD = {
    "device": "solarsense-38BB0B71FE68",
    "ts": 1794226617,
    "v_mv": 0,
    "i_ma": 0.0,
    "irr": 0,
    "temp": 24.21,
    "rh": 61.95,
    "roll": 5.9,
    "pitch": 2.3,
    "heading": 267,
    "rssi": -59,
}


def test_device_payload_parses() -> None:
    p = ReadingPayload.model_validate(DEVICE_PAYLOAD)
    assert p.timestamp == datetime.fromtimestamp(1794226617, UTC)
    assert p.cell_voltage == 0.0
    assert p.ambient_temp == 24.21
    assert p.humidity == 61.95
    assert (p.roll, p.pitch, p.heading, p.rssi) == (5.9, 2.3, 267, -59)


def test_device_millivolts_converted_to_volts() -> None:
    p = ReadingPayload.model_validate({**DEVICE_PAYLOAD, "v_mv": 1840})
    assert p.cell_voltage == pytest.approx(1.84)


def test_device_rssi_optional() -> None:
    payload = {k: v for k, v in DEVICE_PAYLOAD.items() if k != "rssi"}
    assert ReadingPayload.model_validate(payload).rssi is None


def test_device_missing_voltage_rejected() -> None:
    payload = {k: v for k, v in DEVICE_PAYLOAD.items() if k != "v_mv"}
    with pytest.raises(ValidationError):
        ReadingPayload.model_validate(payload)


def test_unsynced_device_clock_rejected() -> None:
    # Before NTP sync the ESP32 reports seconds since boot (i.e. 1970).
    with pytest.raises(ValidationError):
        ReadingPayload.model_validate({**DEVICE_PAYLOAD, "ts": 42})


def test_tilt_combines_roll_and_pitch() -> None:
    base = {
        "id": uuid.uuid4(),
        "site_id": uuid.uuid4(),
        "cell_voltage": 0.0,
        "cell_current": 0.0,
        "ambient_temp": 30.0,
        "humidity": 60.0,
        "heading": 180.0,
        "rssi": None,
        "device_timestamp": datetime.now(UTC),
        "received_at": datetime.now(UTC),
    }
    flat = SensorReadingResponse(**base, roll=0.0, pitch=0.0)
    pitched = SensorReadingResponse(**base, roll=0.0, pitch=15.0)
    both = SensorReadingResponse(**base, roll=5.9, pitch=2.3)
    assert flat.tilt_deg == 0.0
    assert pitched.tilt_deg == pytest.approx(15.0)
    assert both.tilt_deg == pytest.approx(6.33, abs=0.01)
