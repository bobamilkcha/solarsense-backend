from fastapi import status


class VisitsError(Exception):
    """Base class for site visit domain errors surfaced over HTTP."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Site visit error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class VisitNotFoundError(VisitsError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Site visit not found"


class ChecklistItemNotFoundError(VisitsError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Checklist item not found"


class VisitCompletedError(VisitsError):
    status_code = status.HTTP_409_CONFLICT
    detail = "This visit is completed; reopen it before making changes"


class PendingItemsError(VisitsError):
    status_code = status.HTTP_409_CONFLICT
    detail = "Mark every checklist item before completing the visit"
