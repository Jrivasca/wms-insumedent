from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.database import get_database
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.order import OrderStatus
from app.models.packing import PackingTaskStatus
from app.models.picking import PickingLineStatus, PickingTaskStatus
from app.services import inventory_service, packing_service


async def _load_task(tenant_id: str, task_id: str) -> Dict[str, Any]:
    db = get_database()
    task = await db[Collections.PICKING_TASKS].find_one(
        {"_id": to_object_id(task_id), "tenant_id": tenant_id}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Picking task not found")
    return task


def _assert_can_operate(task: Dict[str, Any], user: CurrentUser) -> None:
    if not user.is_supervisor and task.get("assigned_to") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Picking task is not assigned to you",
        )


async def _location_id_by_type(tenant_id: str, warehouse_id: str, loc_type: str) -> Optional[str]:
    db = get_database()
    loc = await db[Collections.LOCATIONS].find_one(
        {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "type": loc_type}
    )
    return str(loc["_id"]) if loc else None


async def list_tasks(
    tenant_id: str,
    user: CurrentUser,
    assigned_to: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if assigned_to == "me":
        query["assigned_to"] = user.id
    elif assigned_to:
        query["assigned_to"] = assigned_to
    if status_filter:
        query["status"] = status_filter
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.PICKING_TASKS].count_documents(query)
    cursor = (
        db[Collections.PICKING_TASKS].find(query).sort("created_at", -1).skip(offset).limit(limit)
    )
    items = [serialize(t) for t in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def get_task(tenant_id: str, task_id: str) -> Dict[str, Any]:
    return serialize(await _load_task(tenant_id, task_id))


async def start_task(tenant_id: str, task_id: str, user: CurrentUser) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)
    if task["status"] in (
        PickingTaskStatus.COMPLETED.value,
        PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
        PickingTaskStatus.CANCELLED.value,
    ):
        raise HTTPException(status_code=409, detail="Picking task is already closed")

    now = now_utc()
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "status": PickingTaskStatus.IN_PROGRESS.value,
                "started_at": task.get("started_at") or now,
                "assigned_to": task.get("assigned_to") or user.id,
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    await db[Collections.ORDERS].update_one(
        {"_id": to_object_id(task["order_id"]), "tenant_id": tenant_id},
        {"$set": {"status": OrderStatus.PICKING.value, "updated_at": now}},
    )
    return serialize(await _load_task(tenant_id, task_id))


async def scan(
    tenant_id: str,
    task_id: str,
    user: CurrentUser,
    barcode: str,
    quantity: float,
    location_id: Optional[str],
) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    if task["status"] in (
        PickingTaskStatus.COMPLETED.value,
        PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
        PickingTaskStatus.CANCELLED.value,
    ):
        raise HTTPException(status_code=409, detail="Picking task is already closed")

    now = now_utc()
    # Auto-start on first scan to keep the floor flow fast.
    if task["status"] == PickingTaskStatus.PENDING.value:
        task["status"] = PickingTaskStatus.IN_PROGRESS.value
        task["started_at"] = now

    code = barcode.strip()
    target_index = None
    for idx, line in enumerate(task["lines"]):
        expected = [str(c).strip() for c in (line.get("barcode_expected") or [])]
        if code in expected:
            target_index = idx
            break

    if target_index is None:
        # Section 8.1: reject a code that does not match the expected product.
        return {
            "status": "rejected",
            "message": f"El código '{code}' no corresponde a ningún producto del pedido",
            "line": None,
            "task": serialize(task),
        }

    line = task["lines"][target_index]
    required = line.get("quantity_required", 0)
    already = line.get("quantity_picked", 0)

    # Block over-picking: never accept more than the order line requires. The scan is
    # rejected (nothing is applied) so the operator is warned and cannot continue.
    if already + quantity > required:
        remaining = max(required - already, 0)
        if remaining <= 0:
            message = f"Este producto ya está completo ({already}/{required}). No escanees de más."
        else:
            name = line.get("name") or line.get("sku")
            message = (
                f"Excede lo pedido: para «{name}» sólo faltan {remaining} de {required}. "
                f"Baja la «cantidad por escaneo»."
            )
        return {
            "status": "rejected",
            "feedback": "warning",
            "message": message,
            "line": line,
            "task": serialize(task),
        }

    new_qty = already + quantity
    line["quantity_picked"] = new_qty
    line.setdefault("scans", []).append(
        {
            "barcode": code,
            "quantity": quantity,
            "location_id": location_id or line.get("suggested_location_id"),
            "user_id": user.id,
            "device": user.user_agent,
            "scanned_at": now,
        }
    )
    if new_qty >= required:
        line["status"] = PickingLineStatus.PICKED.value
        feedback = "complete"
        message = "Línea completa"
    else:
        line["status"] = PickingLineStatus.PARTIAL.value
        feedback = "partial"
        message = f"{new_qty}/{required} unidades"

    task["lines"][target_index] = line
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "lines": task["lines"],
                "status": task["status"],
                "started_at": task.get("started_at"),
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    return {
        "status": "ok",
        "feedback": feedback,
        "message": message,
        "line": line,
        "task": serialize(await _load_task(tenant_id, task_id)),
    }


async def mark_missing(
    tenant_id: str, task_id: str, user: CurrentUser, sku: str, reason: str
) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    found = False
    for line in task["lines"]:
        if line.get("sku") == sku:
            line["status"] = PickingLineStatus.MISSING.value
            line["missing_reason"] = reason
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Line not found for given SKU")

    now = now_utc()
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {"$set": {"lines": task["lines"], "updated_at": now, "updated_by": user.id}},
    )
    return serialize(await _load_task(tenant_id, task_id))


async def reset_line(
    tenant_id: str, task_id: str, user: CurrentUser, sku: str
) -> Dict[str, Any]:
    """Undo a line: set picked back to 0 so it can be scanned again (fix a mistake)."""
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    if task["status"] in (
        PickingTaskStatus.COMPLETED.value,
        PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
        PickingTaskStatus.CANCELLED.value,
    ):
        raise HTTPException(status_code=409, detail="Picking task is already closed")

    found = False
    for line in task["lines"]:
        if line.get("sku") == sku:
            line["quantity_picked"] = 0
            line["status"] = PickingLineStatus.PENDING.value
            line["scans"] = []
            line.pop("missing_reason", None)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Line not found for given SKU")

    now = now_utc()
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {"$set": {"lines": task["lines"], "updated_at": now, "updated_by": user.id}},
    )
    return serialize(await _load_task(tenant_id, task_id))


async def complete(
    tenant_id: str, task_id: str, user: CurrentUser, allow_partial: bool = False
) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    if task["status"] in (
        PickingTaskStatus.COMPLETED.value,
        PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
    ):
        raise HTTPException(status_code=409, detail="Picking task is already completed")

    pending = [
        l
        for l in task["lines"]
        if l.get("status") in (PickingLineStatus.PENDING.value, PickingLineStatus.PARTIAL.value)
    ]
    has_differences = any(
        l.get("status")
        in (
            PickingLineStatus.MISSING.value,
            PickingLineStatus.PARTIAL.value,
            PickingLineStatus.PENDING.value,
        )
        for l in task["lines"]
    )

    if pending and not allow_partial:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Picking has pending lines. A supervisor must authorize partial picking.",
        )
    if pending and allow_partial and not user.is_supervisor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a supervisor can authorize partial picking",
        )

    warehouse_id = task["warehouse_id"]
    staging_id = await _location_id_by_type(tenant_id, warehouse_id, "staging")

    # Record traceable pick movements (floor moves never block).
    for line in task["lines"]:
        qty = line.get("quantity_picked", 0)
        if qty and qty > 0 and line.get("product_id"):
            await inventory_service.register_operational_move(
                tenant_id=tenant_id,
                movement_type=MovementType.PICK.value,
                product_id=line["product_id"],
                warehouse_id=warehouse_id,
                quantity=qty,
                from_location_id=line.get("suggested_location_id"),
                to_location_id=staging_id,
                reference_type=ReferenceType.PICKING_TASK.value,
                reference_id=task_id,
                created_by=user.id,
            )

    now = now_utc()
    new_status = (
        PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value
        if has_differences
        else PickingTaskStatus.COMPLETED.value
    )
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "status": new_status,
                "completed_at": now,
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    await db[Collections.ORDERS].update_one(
        {"_id": to_object_id(task["order_id"]), "tenant_id": tenant_id},
        {"$set": {"status": OrderStatus.PICKED.value, "updated_at": now}},
    )

    # Section 8.2: packing becomes available once picking is closed.
    task = await _load_task(tenant_id, task_id)
    await packing_service.create_packing_task_from_picking(tenant_id, task, user)

    return serialize(task)


async def reopen_picking(tenant_id: str, order_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Retroceso (supervisor): reabrir el picking. El pedido vuelve a 'picking', la tarea
    de picking a 'in_progress' y la de packing se cancela (se regenera al recompletar el
    picking). Ajuste automático: revierte los movimientos de inventario de packing y
    picking (la mercadería vuelve a su ubicación de origen); se re-aplican al recompletar."""
    db = get_database()
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.get("status") not in (
        OrderStatus.PICKED.value,
        OrderStatus.PACKING.value,
        OrderStatus.PACKED.value,
        OrderStatus.READY_TO_DISPATCH.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El pedido no está en una etapa que permita reabrir picking.",
        )
    now = now_utc()
    # Ajuste automático: revertir los movimientos de packing (si los hubo) y de picking.
    packing_tasks = await db[Collections.PACKING_TASKS].find(
        {"tenant_id": tenant_id, "order_id": order_id}
    ).to_list(length=100)
    for pt in packing_tasks:
        await inventory_service.reverse_moves_for_reference(
            tenant_id=tenant_id, reference_type=ReferenceType.PACKING_TASK.value,
            reference_id=str(pt["_id"]), created_by=user.id,
            reason="Reverso por reapertura de picking",
        )
    # Cancelar cualquier tarea de packing activa (se regenerará al recompletar picking).
    await db[Collections.PACKING_TASKS].update_many(
        {"tenant_id": tenant_id, "order_id": order_id,
         "status": {"$ne": PackingTaskStatus.CANCELLED.value}},
        {"$set": {"status": PackingTaskStatus.CANCELLED.value, "updated_at": now,
                  "updated_by": user.id}},
    )
    task = await db[Collections.PICKING_TASKS].find_one(
        {"tenant_id": tenant_id, "order_id": order_id,
         "status": {"$ne": PickingTaskStatus.CANCELLED.value}}
    )
    if task:
        await inventory_service.reverse_moves_for_reference(
            tenant_id=tenant_id, reference_type=ReferenceType.PICKING_TASK.value,
            reference_id=str(task["_id"]), created_by=user.id,
            reason="Reverso por reapertura de picking",
        )
        await db[Collections.PICKING_TASKS].update_one(
            {"_id": task["_id"]},
            {"$set": {"status": PickingTaskStatus.IN_PROGRESS.value, "completed_at": None,
                      "updated_at": now, "updated_by": user.id}},
        )
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"status": OrderStatus.PICKING.value, "updated_at": now}},
    )
    return serialize(await _load_task(tenant_id, str(task["_id"]))) if task else {"status": "reverted"}
