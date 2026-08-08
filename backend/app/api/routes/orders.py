from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.order import OrderLineStatus, OrderStatus
from app.models.sync_job import SyncJobType
from app.schemas.order import OrderCreate, OrderUpdate
from app.services import order_service, packing_service, picking_service, sync_job_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
async def list_orders(
    status: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await order_service.list_orders(user.tenant_id, status, limit, offset)


@router.post("", status_code=201)
async def create_order(
    payload: OrderCreate,
    user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
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

    # Enqueue ERP sync (push the order to Defontana). Best-effort + async.
    # En operación stand-alone (ERP_SYNC_ENABLED=false) no se encola nada.
    if settings.erp_sync_enabled:
        await sync_job_service.enqueue(
            tenant_id=user.tenant_id,
            job_type=SyncJobType.CREATE_ORDER.value,
            payload={
                "order_id": str(doc["_id"]),
                "Number": payload.erp_order_number,
                "Client": {"Name": payload.customer},
                "Detail": [
                    {"Code": ln["sku"], "Name": ln["name"], "Unit": ln["unit"], "Quantity": ln["ordered_quantity"]}
                    for ln in lines
                ],
            },
            created_by=user.id,
        )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="order_create",
        entity_type="order",
        entity_id=str(doc["_id"]),
        metadata={"erp_order_number": payload.erp_order_number},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return serialize(doc)


async def _build_lines(tenant_id: str, lines_input) -> list:
    db = get_database()
    lines = []
    for idx, line in enumerate(lines_input, start=1):
        product = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": tenant_id, "sku": line.sku}
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
    return lines


@router.put("/{order_id}")
async def update_order(
    order_id: str,
    payload: OrderUpdate,
    user: CurrentUser = Depends(require_roles("supervisor")),
):
    """Editar un pedido. Sólo admin/supervisor y sólo antes de generar picking."""
    db = get_database()
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": user.tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.get("status") != OrderStatus.IMPORTED.value:
        raise HTTPException(
            status_code=409,
            detail="Sólo se puede editar un pedido que aún no ha entrado a picking",
        )

    update: Dict[str, Any] = {"updated_at": now_utc(), "updated_by": user.id}
    if payload.customer is not None:
        update["customer"] = payload.customer
    if payload.lines is not None:
        if not payload.lines:
            raise HTTPException(status_code=400, detail="El pedido debe tener al menos una línea")
        update["lines"] = await _build_lines(user.tenant_id, payload.lines)

    await db[Collections.ORDERS].update_one({"_id": order["_id"]}, {"$set": update})
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="order_update",
        entity_type="order",
        entity_id=order_id,
        metadata={"erp_order_number": order.get("erp_order_number")},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return serialize(await db[Collections.ORDERS].find_one({"_id": order["_id"]}))


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


@router.post("/{order_id}/reopen-packing")
async def reopen_packing(
    order_id: str, user: CurrentUser = Depends(require_roles("supervisor"))
):
    """Retroceso: reabrir el packing (el pedido vuelve a 'packing')."""
    result = await packing_service.reopen_packing(user.tenant_id, order_id, user)
    await log_action(
        tenant_id=user.tenant_id, user_id=user.id, action="reopen_packing",
        entity_type="order", entity_id=order_id, metadata={"order_id": order_id},
        ip=user.ip, user_agent=user.user_agent,
    )
    return result


@router.post("/{order_id}/reopen-picking")
async def reopen_picking(
    order_id: str, user: CurrentUser = Depends(require_roles("supervisor"))
):
    """Retroceso: reabrir el picking (el pedido vuelve a 'picking'; cancela packing)."""
    result = await picking_service.reopen_picking(user.tenant_id, order_id, user)
    await log_action(
        tenant_id=user.tenant_id, user_id=user.id, action="reopen_picking",
        entity_type="order", entity_id=order_id, metadata={"order_id": order_id},
        ip=user.ip, user_agent=user.user_agent,
    )
    return result
