from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.warehouse import WarehouseCreate
from app.services import warehouse_service

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("")
async def list_warehouses(user: CurrentUser = Depends(get_current_user)):
    return await warehouse_service.list_warehouses(user.tenant_id)


@router.post("", status_code=201)
async def create_warehouse(
    payload: WarehouseCreate, user: CurrentUser = Depends(require_supervisor)
):
    return await warehouse_service.create_warehouse(user.tenant_id, payload, user.id)


@router.get("/{warehouse_id}/locations")
async def warehouse_locations(
    warehouse_id: str, user: CurrentUser = Depends(get_current_user)
):
    return await warehouse_service.list_locations(user.tenant_id, warehouse_id)
