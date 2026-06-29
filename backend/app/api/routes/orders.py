from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.core.database import get_database
from app.core.utils import now_utc, serialize
from app.models import Collections
from app.models.order import OrderLineStatus, OrderStatus
from app.schemas.order import OrderCreate
from app.services import order_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
async def list_orders(
    status: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await order_service.list_orders(user.tenant_id, status)


@router.post("", status_code=201)
async def create_order(payload: OrderCreate, user: CurrentUser = Depends(require_supervisor)):
    """Manually create / simulate an order (acceptance: import or simulate orders)."""
    db = get_database()
    existing = await db[Collections.ORDERS].find_one(
        {"tenant_id": user.tenant_id, "erp_order_number": payload.erp_order_number}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Order number already exists")

    lines = []
    for idx, line in enumerate(payload.lines, start=1):
        product = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": user.tenant_id, "sku": line.sku}
        )
        lines.append(
            {
                "line_id": f"L{idx}",
                "product_id": str(product["_id"]) if product else None,
                "sku": line.sku,
                "name": line.name or (product.get("name") if product else line.sku),
                "unit": line.unit,
                "ordered_quantity": line.ordered_quantity,
                "picked_quantity": 0,
                "packed_quantity": 0,
                "status": OrderLineStatus.PENDING.value,
            }
        )

    now = now_utc()
    doc = {
        "tenant_id": user.tenant_id,
        "erp_order_number": payload.erp_order_number,
        "erp_document_id": None,
        "customer": payload.customer,
        "status": OrderStatus.IMPORTED.value,
        "order_date": now,
        "delivery_date": None,
        "lines": lines,
        "raw_erp_data": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user.id,
    }
    result = await db[Collections.ORDERS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize(doc)


@router.get("/{order_id}")
async def get_order(order_id: str, user: CurrentUser = Depends(get_current_user)):
    return await order_service.get_order(user.tenant_id, order_id)


@router.post("/{order_id}/create-picking", status_code=201)
async def create_picking(order_id: str, user: CurrentUser = Depends(get_current_user)):
    task = await order_service.create_picking_task(user.tenant_id, order_id, user.id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="create_picking_task",
        entity_type="picking_task",
        entity_id=task["id"],
        metadata={"order_id": order_id},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return task
