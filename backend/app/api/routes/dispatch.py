from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.dispatch import DispatchRequest
from app.services import dispatch_service
from app.services.audit_service import log_action

router = APIRouter(tags=["dispatch"])


@router.post("/orders/{order_id}/dispatch", status_code=201)
async def dispatch_order(
    order_id: str,
    payload: DispatchRequest = DispatchRequest(),
    user: CurrentUser = Depends(require_supervisor),
):
    dispatch = await dispatch_service.confirm_dispatch(
        user.tenant_id, order_id, user, payload.carrier, payload.tracking_number
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="confirm_dispatch",
        entity_type="dispatch",
        entity_id=dispatch["id"],
        metadata={"order_id": order_id, "carrier": payload.carrier},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return dispatch


@router.get("/dispatches")
async def list_dispatches(user: CurrentUser = Depends(get_current_user)):
    return await dispatch_service.list_dispatches(user.tenant_id)


@router.get("/dispatches/{dispatch_id}")
async def get_dispatch(dispatch_id: str, user: CurrentUser = Depends(get_current_user)):
    return await dispatch_service.get_dispatch(user.tenant_id, dispatch_id)
