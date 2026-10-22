from fastapi import status


class UsersError(Exception):
    """Base class for user-management domain errors surfaced over HTTP."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Users error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class UserNotFoundError(UsersError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "User not found"


class InvitationNotFoundError(UsersError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Invitation not found or no longer pending"


class EmailAlreadyRegisteredError(UsersError):
    status_code = status.HTTP_409_CONFLICT
    detail = "A user with this email already exists"


class CannotModifySelfError(UsersError):
    status_code = status.HTTP_409_CONFLICT
    # Stops an admin locking themselves out or leaving the company with no admin.
    detail = "You can't change your own role or deactivate yourself"


class CannotModifySuperAdminError(UsersError):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Only a super_admin can change a super_admin"
