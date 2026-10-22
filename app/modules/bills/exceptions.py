from fastapi import status


class BillsError(Exception):
    """Base class for bill domain errors surfaced over HTTP."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Bills error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class BillNotFoundError(BillsError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Bill not found"


class InvalidPDFError(BillsError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detail = "Could not read the uploaded file as a PDF"
