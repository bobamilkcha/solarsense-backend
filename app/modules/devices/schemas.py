from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

SHORT_CODE_LENGTH = 4

# Range the firmware accepts; it rejects anything outside it.
MIN_PUBLISH_INTERVAL_S = 5
MAX_PUBLISH_INTERVAL_S = 3600
MIN_VALID_YEAR = 2024

Signal = Literal["good", "fair", "weak", "unknown"]


def short_code(device_id: str) -> str:
    """Last few characters of the ID, printed on the device's sticker (e.g. "FE68")."""
    return device_id[-SHORT_CODE_LENGTH:].upper()


def signal_quality(rssi: int | None) -> Signal:
    if rssi is None:
        return "unknown"
    if rssi >= -67:
        return "good"
    if rssi >= -80:
        return "fair"
    return "weak"


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    device_id: str = Field(validation_alias="id")
    first_seen_at: datetime
    last_seen_at: datetime
    last_rssi: int | None

    @computed_field
    @property
    def short_code(self) -> str:
        """Matches the code on the device's sticker; show it in the picker."""
        return short_code(self.device_id)

    @computed_field
    @property
    def signal(self) -> Signal:
        """Wi-Fi strength from `last_rssi`: good (>= -67 dBm), fair (>= -80), weak."""
        return signal_quality(self.last_rssi)


class PairDeviceRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)


class StatusPayload(BaseModel):
    """`solarsense/<device_id>/status`, retained, QoS 1.

    Online:  {"device": "...", "online": true, "fw": "0.3.0",
              "publish_interval_s": 30, "ts": 1794226353}
    Will:    {"device": "...", "online": false}

    The Will carries no fw or interval, so those stay optional.
    """

    model_config = ConfigDict(extra="ignore")

    device: str | None = None
    online: bool
    fw: str | None = None
    publish_interval_s: int | None = None
    ts: datetime | None = None

    @field_validator("ts")
    @classmethod
    def _clock_synced(cls, ts: datetime | None) -> datetime | None:
        return None if ts is not None and ts.year < MIN_VALID_YEAR else ts


PublishInterval = Annotated[
    int, Field(strict=True, ge=MIN_PUBLISH_INTERVAL_S, le=MAX_PUBLISH_INTERVAL_S)
]


class DeviceConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_interval_s: PublishInterval = Field(
        description="Seconds between readings, 5-3600 (the device rejects values outside this)"
    )


class DesiredConfig(BaseModel):
    publish_interval_s: int | None = Field(description="Requested interval; null if never set")
    requested_at: datetime | None


class ReportedStatus(BaseModel):
    online: bool
    fw: str | None = Field(description="Firmware version from the last status message")
    publish_interval_s: int | None = Field(description="What the device is actually using")
    last_seen_at: datetime = Field(description="Last time the device published anything")


class DeviceConfigResponse(BaseModel):
    device_id: str
    desired: DesiredConfig
    reported: ReportedStatus
    synced: bool = Field(
        description="True when nothing is pending (no request, or device confirms it)"
    )


def config_response(device: Any) -> DeviceConfigResponse:
    desired = device.desired_publish_interval_s
    reported = device.reported_publish_interval_s
    return DeviceConfigResponse(
        device_id=device.id,
        desired=DesiredConfig(publish_interval_s=desired, requested_at=device.desired_requested_at),
        reported=ReportedStatus(
            online=device.online,
            fw=device.fw,
            publish_interval_s=reported,
            last_seen_at=device.last_seen_at,
        ),
        synced=desired is None or desired == reported,
    )
