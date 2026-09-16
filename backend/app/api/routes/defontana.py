from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.integration import DefontanaConfigRequest
from app.services import erp_reconcile_service, erp_stock_service, integration_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/integrations/defontana", tags=["defontana"])


@router.get("/status")
async def status(user: CurrentUser = Depends(get_current_user)):
    # Los identificadores de la conexión solo se muestran a supervisores (nunca contraseñas).
    return await integration_service.get_status(
        user.tenant_id, include_credentials=user.is_supervisor
    )


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


@router.post("/sync-orders")
async def sync_orders(user: CurrentUser = Depends(require_supervisor)):
    return await integration_service.run_sync_orders(user.tenant_id, user.id)


@router.post("/sync-stock")
async def sync_stock(user: CurrentUser = Depends(require_supervisor)):
    """Trae la foto de stock de Defontana (solo lectura: no modifica el stock del WMS)."""
    return await integration_service.run_sync_stock(user.tenant_id, user.id)


@router.get("/stock-comparison")
async def stock_comparison(
    only_diff: bool = True,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(require_supervisor),
):
    """Stock de Defontana vs stock del WMS por SKU y bodega (informativo)."""
    return await erp_stock_service.compare(
        user.tenant_id, only_diff=only_diff, q=q, limit=limit, offset=offset
    )


@router.get("/reconciliation-preview")
async def reconciliation_preview(
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(require_supervisor),
):
    """Qué ajustaría la conciliación para dejar el stock del WMS igual al de Defontana.
    Solo calcula: no modifica saldos ni movimientos."""
    return await erp_reconcile_service.preview(user.tenant_id, q=q, limit=limit, offset=offset)
