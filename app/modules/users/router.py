import uuid

from app.models import UserRole
from app.modules.auth.deps import CurrentUser, company_scope, require_roles
from app.modules.auth.schemas import UserResponse
from app.modules.users import schemas
from app.modules.users.deps import UsersServiceDep
from fastapi import APIRouter, status

router = APIRouter(prefix="/users", tags=["users"])

admin_only = [require_roles(UserRole.COMPANY_ADMIN)]


@router.get("", response_model=list[UserResponse])
async def list_users(current_user: CurrentUser, service: UsersServiceDep):
    """Everyone in the caller's company (any role can see their teammates)."""
    return await service.list_users(company_scope(current_user))


@router.post(
    "/invitations",
    response_model=schemas.InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=admin_only,
)
async def create_invitation(
    data: schemas.InvitationCreateRequest, current_user: CurrentUser, service: UsersServiceDep
):
    invitation, token = await service.create_invitation(current_user, data)
    return schemas.InvitationCreatedResponse(
        **schemas.InvitationResponse.model_validate(invitation).model_dump(), token=token
    )


@router.get(
    "/invitations",
    response_model=list[schemas.InvitationResponse],
    dependencies=admin_only,
)
async def list_invitations(current_user: CurrentUser, service: UsersServiceDep):
    return await service.list_pending_invitations(company_scope(current_user))


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=admin_only,
)
async def revoke_invitation(
    invitation_id: uuid.UUID, current_user: CurrentUser, service: UsersServiceDep
):
    await service.revoke_invitation(company_scope(current_user), invitation_id)


@router.patch("/{user_id}", response_model=UserResponse, dependencies=admin_only)
async def update_user(
    user_id: uuid.UUID,
    data: schemas.UserUpdateRequest,
    current_user: CurrentUser,
    service: UsersServiceDep,
):
    return await service.update_user(current_user, user_id, data)
