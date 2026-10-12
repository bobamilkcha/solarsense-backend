from fastapi import status


class ProjectsError(Exception):
    """Base class for project/site domain errors.

    Subclasses carry the HTTP status code and client-facing detail used by the
    global exception handler, so routers stay free of try/except mapping.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Projects error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class ProjectNotFoundError(ProjectsError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Project not found"


class DeviceIdAlreadyExistsError(ProjectsError):
    status_code = status.HTTP_409_CONFLICT
    detail = "A site with this device_id already exists"
