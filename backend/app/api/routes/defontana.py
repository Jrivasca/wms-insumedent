from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.integration import DefontanaConfigRequest
from app.services import integration_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/integrations/defontana", tags=["defontana"])


@router.get("/status")
async def status(user: CurrentUser = Depends(get_current_user)):
    return await integration_service.get_status(user.tenant_id)


@router.post("/configure")
async def configure(
    payload: DefontanaConfigRequest, user: CurrentUser = Depends(require_supervisor)
):
    result = await integration_service.configure(user.tenant_id, payload, user.id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="configure_defontana",
        entity_type="erp_connection",
        entity_id=user.tenant_id,
        after={"environment": payload.environment.value, "auth_mode": payload.auth_mode.value},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/check")
async def check(user: CurrentUser = Depends(require_supervisor)):
    return await integration_service.check(user.tenant_id)


@router.post("/sync-products")
async def sync_products(user: CurrentUser = Depends(require_supervisor)):
    return await integration_service.run_sync_products(user.tenant_id, user.id)


@router.post("/sync-warehouses")
async def sync_warehouses(user: CurrentUser = Depends(require_supervisor)):
    return await integration_service.run_sync_warehouses(user.tenant_id, user.id)


@router.post("/sync-orders")
async def sync_orders(user: CurrentUser = Depends(require_supervisor)):
    return await integration_service.run_sync_orders(user.tenant_id, user.id)
