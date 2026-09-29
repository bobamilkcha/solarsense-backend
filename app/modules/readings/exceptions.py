from fastapi import status


class UnknownDeviceError(Exception):
    """Raised when a reading arrives for a device_id with no matching Site."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"No site registered for device_id={device_id!r}")


class ReadingsError(Exception):
    """Base class for readings domain errors surfaced over HTTP.

    Subclasses carry the HTTP status code and client-facing detail used by the
    global exception handler, so routers stay free of try/except mapping.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Readings error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class SiteNotFoundError(ReadingsError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Site not found"
