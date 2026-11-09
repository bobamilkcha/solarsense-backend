import uuid
from datetime import timedelta

from app.models import UserRole
from app.modules.auth.deps import CurrentUser, company_scope, require_roles
from app.modules.devices import schemas
from app.modules.devices.deps import ConfigPublisherDep, DevicesServiceDep
from app.modules.readings.schemas import SiteResponse
from fastapi import APIRouter, Query

# Pairing is an admin task, like creating sites.
router = APIRouter(
    prefix="/devices", tags=["devices"], dependencies=[require_roles(UserRole.COMPANY_ADMIN)]
)
sites_router = APIRouter(
    prefix="/sites", tags=["devices"], dependencies=[require_roles(UserRole.COMPANY_ADMIN)]
)


@router.get("/unpaired", response_model=list[schemas.DeviceResponse])
async def list_unpaired_devices(
    service: DevicesServiceDep,
    within_minutes: int = Query(
        default=10, ge=1, le=1440, description="Only devices that published this recently"
    ),
):
    """Devices that are online but not paired to any site, for the pairing picker."""
    return await service.list_unpaired(timedelta(minutes=within_minutes))


@router.get("/{device_id}/config", response_model=schemas.DeviceConfigResponse)
async def get_device_config(device_id: str, current_user: CurrentUser, service: DevicesServiceDep):
    """Requested config and what the device reports it is using.

    `synced` is false while a requested change has not been confirmed by the
    device's status message; poll this until it flips to true.
    """
    device = await service.get_config(device_id, company_scope(current_user))
    return schemas.config_response(device)


@router.put("/{device_id}/config", response_model=schemas.DeviceConfigResponse)
async def set_device_config(
    device_id: str,
    data: schemas.DeviceConfigRequest,
    current_user: CurrentUser,
    service: DevicesServiceDep,
    publisher: ConfigPublisherDep,
):
    """Request a new publish interval (5-3600 s). Retained, so an offline device gets it later."""
    device = await service.set_desired_config(
        device_id, company_scope(current_user), publisher, data.publish_interval_s
    )
    return schemas.config_response(device)


@sites_router.put("/{site_id}/device", response_model=SiteResponse)
async def pair_device(
    site_id: uuid.UUID,
    data: schemas.PairDeviceRequest,
    current_user: CurrentUser,
    service: DevicesServiceDep,
):
    """Pair a device to the site. Replaces the site's current device, if any."""
    return await service.pair(site_id, company_scope(current_user), data.device_id)


@sites_router.delete("/{site_id}/device", response_model=SiteResponse)
async def unpair_device(site_id: uuid.UUID, current_user: CurrentUser, service: DevicesServiceDep):
    """Release the site's device so it can be moved to another site."""
    return await service.unpair(site_id, company_scope(current_user))
