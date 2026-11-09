"""Unit tests for status payload parsing and the config request range."""

import pytest
from app.modules.devices.schemas import DeviceConfigRequest, StatusPayload
from pydantic import ValidationError


def test_online_status_parses() -> None:
    s = StatusPayload.model_validate(
        {
            "device": "solarsense-38BB0B71FE68",
            "online": True,
            "fw": "0.3.0",
            "publish_interval_s": 30,
            "ts": 1794226353,
        }
    )
    assert s.online and s.fw == "0.3.0" and s.publish_interval_s == 30
    assert s.ts is not None


def test_offline_will_has_no_fw_or_interval() -> None:
    s = StatusPayload.model_validate({"device": "solarsense-38BB0B71FE68", "online": False})
    assert not s.online
    assert s.fw is None and s.publish_interval_s is None and s.ts is None


@pytest.mark.parametrize("value", [5, 30, 3600])
def test_interval_in_range_accepted(value: int) -> None:
    assert DeviceConfigRequest(publish_interval_s=value).publish_interval_s == value


@pytest.mark.parametrize("value", [0, 4, 3601, -1, "30", 30.5, True])
def test_interval_out_of_range_or_wrong_type_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        DeviceConfigRequest.model_validate({"publish_interval_s": value})
