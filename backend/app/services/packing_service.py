import secrets
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.order import OrderStatus
from app.models.packing import PackingLineStatus, PackingTaskStatus
from app.services import inventory_service
from app.services.order_service import _expected_barcodes


def _new_public_token() -> str:
    """Unguessable capability token for a bulto's public QR page (128 bits)."""
    return secrets.token_urlsafe(16)


def _public_expiry():
    return now_utc() + timedelta(days=settings.public_bulto_ttl_days)


async def _ensure_public_tokens(task: Dict[str, Any]) -> None:
    """Backfill a public token + expiry on any package that lacks one (idempotent)."""
    packages = task.get("packages", [])
    changed = False
    for pkg in packages:
        if not pkg.get("public_token"):
            pkg["public_token"] = _new_public_token()
            pkg["public_expires_at"] = _public_expiry()
            changed = True
    if changed:
        db = get_database()
        await db[Collections.PACKING_TASKS].update_one(
            {"_id": task["_id"]}, {"$set": {"packages": packages}}
        )


async def _load_task(tenant_id: str, task_id: str) -> Dict[str, Any]:
    db = get_database()
    task = await db[Collections.PACKING_TASKS].find_one(
        {"_id": to_object_id(task_id), "tenant_id": tenant_id}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Packing task not found")
    return task


def _assert_can_operate(task: Dict[str, Any], user: CurrentUser) -> None:
    if not user.is_supervisor and task.get("assigned_to") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Packing task is not assigned to you",
        )


async def _location_id_by_type(tenant_id: str, warehouse_id: str, loc_type: str) -> Optional[str]:
    db = get_database()
    loc = await db[Collections.LOCATIONS].find_one(
        {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "type": loc_type}
    )
    return str(loc["_id"]) if loc else None


async def create_packing_task_from_picking(
    tenant_id: str, picking_task: Dict[str, Any], user: CurrentUser
) -> Dict[str, Any]:
    """Create the packing task that follows a closed picking task (section 8.2)."""
    db = get_database()
    existing = await db[Collections.PACKING_TASKS].find_one(
        {
            "tenant_id": tenant_id,
            "picking_task_id": str(picking_task["_id"]),
            "status": {"$nin": [PackingTaskStatus.CANCELLED.value]},
        }
    )
    if existing:
        return serialize(existing)

    lines = []
    for line in picking_task.get("lines", []):
        picked = line.get("quantity_picked", 0)
        if not picked:
            continue
        expected = (
            await _expected_barcodes(tenant_id, line["product_id"], line.get("sku", ""))
            if line.get("product_id")
            else [line.get("sku")]
        )
        lines.append(
            {
                "product_id": line.get("product_id"),
                "sku": line.get("sku"),
                "name": line.get("name"),
                "barcode_expected": expected,
                "quantity_required": picked,
                "quantity_packed": 0,
                "status": PackingLineStatus.PENDING.value,
            }
        )

    now = now_utc()
    task = {
        "tenant_id": tenant_id,
        "order_id": picking_task["order_id"],
        "erp_order_number": picking_task.get("erp_order_number"),
        "picking_task_id": str(picking_task["_id"]),
        "warehouse_id": picking_task.get("warehouse_id"),
        "assigned_to": picking_task.get("assigned_to"),
        "status": PackingTaskStatus.PENDING.value,
        "packages": [],
        "lines": lines,
        "started_at": None,
        "completed_at": None,
        "created_by": user.id,
        "updated_by": user.id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.PACKING_TASKS].insert_one(task)
    task["_id"] = result.inserted_id
    return serialize(task)


async def list_tasks(
    tenant_id: str, user: CurrentUser, assigned_to: Optional[str] = None
) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if assigned_to == "me":
        query["assigned_to"] = user.id
    elif assigned_to:
        query["assigned_to"] = assigned_to
    cursor = db[Collections.PACKING_TASKS].find(query).sort("created_at", -1)
    return [serialize(t) for t in await cursor.to_list(length=500)]


async def get_task(tenant_id: str, task_id: str) -> Dict[str, Any]:
    task = await _load_task(tenant_id, task_id)
    await _ensure_public_tokens(task)  # backfill QR tokens for bultos created before this feature
    return serialize(task)


async def start_task(tenant_id: str, task_id: str, user: CurrentUser) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    # Section 8.2: packing only starts once picking is closed.
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(task["order_id"]), "tenant_id": tenant_id}
    )
    if order and order.get("status") not in (
        OrderStatus.PICKED.value,
        OrderStatus.PACKING.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Packing can only start after picking is completed",
        )

    now = now_utc()
    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "status": PackingTaskStatus.IN_PROGRESS.value,
                "started_at": task.get("started_at") or now,
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    await db[Collections.ORDERS].update_one(
        {"_id": to_object_id(task["order_id"]), "tenant_id": tenant_id},
        {"$set": {"status": OrderStatus.PACKING.value, "updated_at": now}},
    )
    return serialize(await _load_task(tenant_id, task_id))


async def scan(
    tenant_id: str,
    task_id: str,
    user: CurrentUser,
    barcode: str,
    quantity: float,
    package_id: Optional[str],
) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)
    if task["status"] in (PackingTaskStatus.COMPLETED.value, PackingTaskStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail="Packing task is already closed")

    now = now_utc()
    if task["status"] == PackingTaskStatus.PENDING.value:
        task["status"] = PackingTaskStatus.IN_PROGRESS.value
        task["started_at"] = now

    code = barcode.strip()
    target_index = None
    for idx, line in enumerate(task["lines"]):
        expected = [str(c).strip() for c in (line.get("barcode_expected") or [])]
        if code in expected:
            target_index = idx
            break

    if target_index is None:
        return {
            "status": "rejected",
            "message": f"El código '{code}' no corresponde a este pedido",
            "line": None,
            "task": serialize(task),
        }

    line = task["lines"][target_index]
    required = line.get("quantity_required", 0)
    new_qty = line.get("quantity_packed", 0) + quantity
    line["quantity_packed"] = new_qty

    if new_qty > required:
        line["status"] = PackingLineStatus.PARTIAL.value
        feedback, message = "warning", "Cantidad supera lo pickeado (diferencia)"
    elif new_qty == required:
        line["status"] = PackingLineStatus.PACKED.value
        feedback, message = "complete", "Línea completa"
    else:
        line["status"] = PackingLineStatus.PARTIAL.value
        feedback, message = "partial", f"{new_qty}/{required} unidades"

    # Optionally register the unit into a package.
    if package_id:
        for pkg in task.get("packages", []):
            if pkg.get("package_id") == package_id:
                pkg.setdefault("items", []).append(
                    {"sku": line.get("sku"), "quantity": quantity}
                )
                break

    task["lines"][target_index] = line
    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "lines": task["lines"],
                "packages": task.get("packages", []),
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


async def create_package(
    tenant_id: str, task_id: str, user: CurrentUser, label: Optional[str]
) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    package_number = len(task.get("packages", [])) + 1
    package = {
        "package_id": f"PKG-{package_number}",
        "label": label or f"Bulto {package_number}",
        "items": [],
        "public_token": _new_public_token(),
        "public_expires_at": _public_expiry(),
        "created_at": now_utc(),
    }
    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]},
        {"$push": {"packages": package}, "$set": {"updated_at": now_utc()}},
    )
    return package


async def reset_line(
    tenant_id: str, task_id: str, user: CurrentUser, sku: str
) -> Dict[str, Any]:
    """Undo a packed line: set packed back to 0 and remove its items from every
    package, so it can be packed again (fix a mistake). Inventory is only touched
    on complete(), so nothing to revert there."""
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    if task["status"] in (
        PackingTaskStatus.COMPLETED.value,
        PackingTaskStatus.CANCELLED.value,
    ):
        raise HTTPException(status_code=409, detail="Packing task is already closed")

    found = False
    for line in task["lines"]:
        if line.get("sku") == sku:
            line["quantity_packed"] = 0
            line["status"] = PackingLineStatus.PENDING.value
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Line not found for given SKU")

    # Drop this SKU's items from every package.
    for pkg in task.get("packages", []):
        pkg["items"] = [it for it in pkg.get("items", []) if it.get("sku") != sku]

    now = now_utc()
    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "lines": task["lines"],
                "packages": task.get("packages", []),
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    return serialize(await _load_task(tenant_id, task_id))


async def complete(tenant_id: str, task_id: str, user: CurrentUser) -> Dict[str, Any]:
    db = get_database()
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)

    if task["status"] == PackingTaskStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Packing task is already completed")

    differences = any(
        line.get("quantity_packed", 0) != line.get("quantity_required", 0)
        for line in task["lines"]
    )

    now = now_utc()
    # Section 8.2: differences require supervisor approval; otherwise -> observed.
    if differences and not user.is_supervisor:
        await db[Collections.PACKING_TASKS].update_one(
            {"_id": task["_id"]},
            {
                "$set": {
                    "status": PackingTaskStatus.OBSERVED.value,
                    "updated_at": now,
                    "updated_by": user.id,
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Packing differs from picking. Supervisor approval required (task marked observed).",
        )

    warehouse_id = task.get("warehouse_id")
    staging_id = await _location_id_by_type(tenant_id, warehouse_id, "staging") if warehouse_id else None
    packing_id = await _location_id_by_type(tenant_id, warehouse_id, "packing") if warehouse_id else None

    for line in task["lines"]:
        qty = line.get("quantity_packed", 0)
        if qty and qty > 0 and line.get("product_id"):
            await inventory_service.register_operational_move(
                tenant_id=tenant_id,
                movement_type=MovementType.PACK.value,
                product_id=line["product_id"],
                warehouse_id=warehouse_id,
                quantity=qty,
                from_location_id=staging_id,
                to_location_id=packing_id,
                reference_type=ReferenceType.PACKING_TASK.value,
                reference_id=task_id,
                created_by=user.id,
            )

    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]},
        {
            "$set": {
                "status": PackingTaskStatus.COMPLETED.value,
                "completed_at": now,
                "approved_by": user.id if differences else None,
                "updated_at": now,
                "updated_by": user.id,
            }
        },
    )
    await db[Collections.ORDERS].update_one(
        {"_id": to_object_id(task["order_id"]), "tenant_id": tenant_id},
        {"$set": {"status": OrderStatus.READY_TO_DISPATCH.value, "updated_at": now}},
    )
    return serialize(await _load_task(tenant_id, task_id))
