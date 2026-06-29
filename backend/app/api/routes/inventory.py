from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.core.utils import serialize
from app.schemas.inventory import AdjustmentRequest, TransferRequest
from app.services import inventory_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/balances")
async def balances(
    product_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    location_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
):
    return await inventory_service.list_balances(
        user.tenant_id, product_id, warehouse_id, location_id
    )


@router.get("/movements")
async def movements(
    product_id: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await inventory_service.list_movements(user.tenant_id, product_id)


@router.post("/adjustments")
async def create_adjustment(
    payload: AdjustmentRequest, user: CurrentUser = Depends(require_supervisor)
):
    # Section 8.4: adjustments must be approved by a supervisor.
    balance = await inventory_service.create_adjustment(
        tenant_id=user.tenant_id,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        location_id=payload.location_id,
        quantity=payload.quantity,
        reason=payload.reason,
        created_by=user.id,
        lot_number=payload.lot_number,
        serial_number=payload.serial_number,
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="inventory_adjustment",
        entity_type="inventory_balance",
        entity_id=payload.product_id,
        after={"quantity": payload.quantity, "reason": payload.reason},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return serialize(balance)


@router.post("/transfers")
async def create_transfer(
    payload: TransferRequest, user: CurrentUser = Depends(get_current_user)
):
    await inventory_service.create_transfer(
        tenant_id=user.tenant_id,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        quantity=payload.quantity,
        created_by=user.id,
        lot_number=payload.lot_number,
        serial_number=payload.serial_number,
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="inventory_transfer",
        entity_type="inventory_balance",
        entity_id=payload.product_id,
        after={
            "from": payload.from_location_id,
            "to": payload.to_location_id,
            "quantity": payload.quantity,
        },
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return {"status": "ok"}
