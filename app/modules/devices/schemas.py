from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

SHORT_CODE_LENGTH = 4

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
