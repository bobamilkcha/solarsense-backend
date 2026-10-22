from fastapi import status


class ReportsError(Exception):
    """Base class for report domain errors surfaced over HTTP."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Reports error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class NoBillDataError(ReportsError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detail = "Upload at least one TNB bill with readable kWh usage before generating a report"


class IrradiationUnavailableError(ReportsError):
    status_code = status.HTTP_502_BAD_GATEWAY
    detail = "Satellite irradiation data (PVGIS) is unavailable right now"
