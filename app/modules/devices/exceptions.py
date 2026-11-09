from fastapi import status


class DevicesError(Exception):
    """Base class for device pairing errors surfaced over HTTP.

    Subclasses carry the HTTP status code and client-facing detail used by the
    global exception handler, so routers stay free of try/except mapping.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Devices error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class DeviceAlreadyPairedError(DevicesError):
    status_code = status.HTTP_409_CONFLICT
    detail = "This device is already paired to another site; unpair it there first"


class DeviceNotFoundError(DevicesError):
    # Also used for a device paired to another company's site, so IDs aren't confirmed.
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Device not found, or not paired to one of your sites"


class MQTTUnavailableError(DevicesError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = "Cannot reach the MQTT broker right now; the change was not saved"
