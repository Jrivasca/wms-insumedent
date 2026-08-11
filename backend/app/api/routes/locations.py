from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.warehouse import LocationCreate, LocationUpdate
from app.services import warehouse_service

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("")
async def list_locations(
    warehouse_id: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await warehouse_service.list_locations(user.tenant_id, warehouse_id, user)


@router.post("", status_code=201)
async def create_location(
    payload: LocationCreate, user: CurrentUser = Depends(require_supervisor)
):
    return await warehouse_service.create_location(user.tenant_id, payload, user.id)


@router.put("/{location_id}")
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    user: CurrentUser = Depends(require_supervisor),
):
    return await warehouse_service.update_location(
        user.tenant_id, location_id, payload, user.id
    )
