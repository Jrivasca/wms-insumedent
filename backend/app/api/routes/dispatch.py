from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_roles, require_supervisor
from app.schemas.dispatch import DispatchRequest
from app.services import dispatch_service
from app.services.audit_service import log_action

router = APIRouter(tags=["dispatch"])


@router.post("/orders/{order_id}/dispatch", status_code=201)
async def dispatch_order(
    order_id: str,
    payload: DispatchRequest = DispatchRequest(),
    user: CurrentUser = Depends(require_roles("supervisor", "dispatcher")),
):
    dispatch = await dispatch_service.confirm_dispatch(
        user.tenant_id, order_id, user,
        carrier=payload.carrier,
        tracking_number=payload.tracking_number,
        guide_number=payload.guide_number,
        package_ids=payload.package_ids,
        lines=[l.model_dump() for l in payload.lines] if payload.lines else None,
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="confirm_dispatch",
        entity_type="dispatch",
        entity_id=dispatch["id"],
        metadata={"order_id": order_id, "carrier": payload.carrier,
                  "guide_number": payload.guide_number},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return dispatch


@router.post("/orders/{order_id}/dispatch/cancel")
async def cancel_dispatch(
    order_id: str, user: CurrentUser = Depends(require_supervisor)
):
    """Retroceso: anular TODAS las guías del pedido (vuelve a 'listo para despacho')."""
    result = await dispatch_service.cancel_dispatch(user.tenant_id, order_id, user)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="cancel_dispatch",
        entity_type="order",
        entity_id=order_id,
        metadata={"order_id": order_id},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/dispatches/{dispatch_id}/cancel")
async def cancel_one_dispatch(
    dispatch_id: str, user: CurrentUser = Depends(require_supervisor)
):
    """Anular UNA guía puntual (el resto del pedido sigue su curso)."""
    result = await dispatch_service.cancel_dispatch_by_id(user.tenant_id, dispatch_id, user)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="cancel_dispatch",
        entity_type="dispatch",
        entity_id=dispatch_id,
        metadata={"dispatch_id": dispatch_id},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.get("/orders/{order_id}/dispatches")
async def list_order_dispatches(
    order_id: str, user: CurrentUser = Depends(get_current_user)
):
    return await dispatch_service.list_order_dispatches(user.tenant_id, order_id)


@router.get("/dispatches")
async def list_dispatches(
    limit: int = 500,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await dispatch_service.list_dispatches(user.tenant_id, limit, offset)


@router.get("/dispatches/{dispatch_id}")
async def get_dispatch(dispatch_id: str, user: CurrentUser = Depends(get_current_user)):
    return await dispatch_service.get_dispatch(user.tenant_id, dispatch_id)
