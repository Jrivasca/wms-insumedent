from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.core.utils import serialize
from app.schemas.inventory import AdjustmentRequest, ReceptionRequest, TransferRequest
from app.services import inventory_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _aware(dt):
    """Normalize a parsed date/datetime to timezone-aware UTC (dates arrive naive)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/balances")
async def balances(
    product_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    location_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await inventory_service.list_balances(
        user.tenant_id, product_id, warehouse_id, location_id, limit, offset, user=user
    )


@router.get("/movements")
async def movements(
    product_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await inventory_service.list_movements(
        user.tenant_id, product_id, limit, offset, user=user
    )


@router.post("/receptions", status_code=201)
async def create_reception(
    payload: ReceptionRequest, user: CurrentUser = Depends(get_current_user)
):
    user.assert_warehouse_allowed(payload.warehouse_id)
    result = await inventory_service.create_reception(
        tenant_id=user.tenant_id,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        location_id=payload.location_id,
        quantity=payload.quantity,
        created_by=user.id,
        reference=payload.reference,
        lot_number=payload.lot_number,
        serial_number=payload.serial_number,
        expiration_date=_aware(payload.expiration_date),
        sync_erp=payload.sync_erp,
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="inventory_reception",
        entity_type="inventory_balance",
        entity_id=payload.product_id,
        after={
            "location_id": payload.location_id,
            "quantity": payload.quantity,
            "reference": payload.reference,
        },
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/adjustments")
async def create_adjustment(
    payload: AdjustmentRequest, user: CurrentUser = Depends(require_supervisor)
):
    # Section 8.4: adjustments must be approved by a supervisor.
    user.assert_warehouse_allowed(payload.warehouse_id)
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
    user.assert_warehouse_allowed(payload.warehouse_id)
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
