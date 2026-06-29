from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.order import OrderStatus
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
) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if assigned_to == "me":
        query["assigned_to"] = user.id
    elif assigned_to:
        query["assigned_to"] = assigned_to
    if status_filter:
        query["status"] = status_filter
    cursor = db[Collections.PICKING_TASKS].find(query).sort("created_at", -1)
    return [serialize(t) for t in await cursor.to_list(length=500)]


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
    new_qty = already + quantity
    over = new_qty > required
    applied_qty = min(new_qty, required)

    line["quantity_picked"] = applied_qty
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
    if applied_qty >= required:
        line["status"] = PickingLineStatus.PICKED.value
        feedback = "complete"
        message = "Línea completa"
    else:
        line["status"] = PickingLineStatus.PARTIAL.value
        feedback = "partial"
        message = f"{applied_qty}/{required} unidades"
    if over:
        feedback = "warning"
        message = "Cantidad solicitada alcanzada (escaneo excedente ignorado)"

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
