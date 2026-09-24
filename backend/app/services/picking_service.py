from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.order import OrderFulfillment, OrderStatus
from app.models.packing import PackingTaskStatus
from app.models.picking import PickingLineStatus, PickingTaskStatus
from app.services import (
    integration_service,
    inventory_service,
    order_service,
    packing_service,
    replenishment_alert_service,
)


async def _load_task(tenant_id: str, task_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    task = await db[Collections.PICKING_TASKS].find_one(
        {"_id": to_object_id(task_id), "tenant_id": tenant_id}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Picking task not found")
    return task


def _assert_can_operate(task: Dict[str, Any], user: CurrentUser) -> None:
    user.assert_warehouse_allowed(task.get("warehouse_id"))
    if not user.is_supervisor and task.get("assigned_to") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Picking task is not assigned to you",
        )


async def _location_id_by_type(tenant_id: str, warehouse_id: str, loc_type: str) -> Optional[str]:
    db = tenant_db(tenant_id)
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
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if assigned_to == "me":
        query["assigned_to"] = user.id
    elif assigned_to:
        query["assigned_to"] = assigned_to
    if status_filter:
        query["status"] = status_filter
    else:
        # Ocultar las canceladas (quedan solo como auditoría) de las listas de trabajo.
        query["status"] = {"$ne": PickingTaskStatus.CANCELLED.value}
    if user.warehouse_scoped:
        query["warehouse_id"] = {"$in": list(user.allowed_warehouse_ids)}
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.PICKING_TASKS].count_documents(query)
    cursor = (
        db[Collections.PICKING_TASKS].find(query).sort("created_at", -1).skip(offset).limit(limit)
    )
    items = [serialize(t) for t in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def get_task(tenant_id: str, task_id: str, user: CurrentUser) -> Dict[str, Any]:
    task = await _load_task(tenant_id, task_id)
    user.assert_warehouse_allowed(task.get("warehouse_id"))
    return serialize(task)


async def start_task(tenant_id: str, task_id: str, user: CurrentUser) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
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
    lot_number: Optional[str] = None,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
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

    # Lote: el operario elige de la lista FEFO. Para un producto que maneja lotes es
    # obligatorio (no se confirma sin lote); se valida contra el stock pickeable y se guarda el
    # lote + vencimiento en el scan, para que viaje hasta la guía de despacho.
    product_id = line.get("product_id")
    lots = (
        await inventory_service.available_lots(tenant_id, product_id, task["warehouse_id"])
        if product_id else []
    )
    manages_lots = any(l.get("lot_number") for l in lots)
    scan_lot: Optional[str] = None
    scan_expiration = None
    if manages_lots:
        if not lot_number:
            return {
                "status": "rejected",
                "feedback": "warning",
                "message": "Este producto maneja lotes: elegí el lote de la lista antes de confirmar.",
                "line": line,
                "task": serialize(task),
            }
        loc = location_id or line.get("suggested_location_id")
        balance = next(
            (l for l in lots
             if l.get("lot_number") == lot_number and l.get("location_id") == loc),
            None,
        ) or next((l for l in lots if l.get("lot_number") == lot_number), None)
        if balance is None:
            return {
                "status": "rejected",
                "feedback": "warning",
                "message": (
                    f"El lote «{lot_number}» ya no tiene stock pickeable. "
                    "Actualizá los lotes desde Defontana o elegí otro."
                ),
                "line": line,
                "task": serialize(task),
            }
        scan_lot = lot_number
        scan_expiration = balance.get("expiration_date")
        location_id = balance["location_id"]
        already_lot = sum(
            s.get("quantity", 0) for s in line.get("scans", [])
            if s.get("lot_number") == lot_number and s.get("location_id") == location_id
        )
        if already_lot + quantity > (balance.get("quantity_on_hand") or 0):
            quedan = max((balance.get("quantity_on_hand") or 0) - already_lot, 0)
            return {
                "status": "rejected",
                "feedback": "warning",
                "message": f"No hay suficiente del lote «{lot_number}» en esa ubicación: quedan {quedan:g}.",
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
            "lot_number": scan_lot,
            "expiration_date": scan_expiration,
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


async def available_lots(
    tenant_id: str, task_id: str, line_id: str, user: CurrentUser
) -> Dict[str, Any]:
    """Lotes que el operario puede elegir para una línea: el stock pickeable ordenado FEFO,
    restando lo ya escaneado en la línea para no comprometer el mismo lote de más. ``manages_lots``
    dice si el producto maneja lotes (si es False, la pantalla sigue con el escaneo simple)."""
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)
    line = next((l for l in task["lines"] if l.get("line_id") == line_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Línea no encontrada")
    lots = (
        await inventory_service.available_lots(tenant_id, line["product_id"], task["warehouse_id"])
        if line.get("product_id") else []
    )
    picked: Dict[Any, float] = {}
    for s in line.get("scans", []):
        key = (s.get("location_id"), s.get("lot_number"))
        picked[key] = picked.get(key, 0) + (s.get("quantity", 0) or 0)
    out = []
    for l in lots:
        remaining = (l.get("quantity_on_hand") or 0) - picked.get(
            (l.get("location_id"), l.get("lot_number")), 0
        )
        if remaining > 0:
            out.append({**l, "quantity_available": remaining})
    return {
        "line_id": line_id,
        "manages_lots": any(l.get("lot_number") for l in lots),
        "lots": [serialize(l) for l in out],
    }


def _line_or_404(task: Dict[str, Any], line_id: str) -> Dict[str, Any]:
    line = next((l for l in task["lines"] if l.get("line_id") == line_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Línea no encontrada")
    return line


async def erp_lots(
    tenant_id: str, task_id: str, line_id: str, user: CurrentUser
) -> Dict[str, Any]:
    """Lotes que Defontana informa para el producto de la línea (foto ``erp_batches``): son los
    candidatos correctos cuando el lote del saldo del WMS está mal ingresado. Alimenta 'Corregir
    lote'. Ordenados FEFO."""
    db = tenant_db(tenant_id)
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)
    line = _line_or_404(task, line_id)
    out: List[Dict[str, Any]] = []
    async for b in db[Collections.ERP_BATCHES].find({"sku": line.get("sku")}):
        if not b.get("lot_number"):
            continue
        out.append({
            "lot_number": b.get("lot_number"),
            "expiration_date": b.get("expiration_date"),
            "stock": b.get("stock"),
            "storage_code": b.get("storage_code"),
        })
    out.sort(key=lambda r: (r["expiration_date"] is None, r["expiration_date"] or datetime.max))
    return {"line_id": line_id, "sku": line.get("sku"), "lots": [serialize(x) for x in out]}


async def correct_lot(
    tenant_id: str,
    task_id: str,
    line_id: str,
    user: CurrentUser,
    *,
    location_id: str,
    from_lot_number: Optional[str],
    to_lot_number: str,
    to_expiration_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Corrige el lote mal ingresado de un saldo por el correcto (Parte 3, opción A). Es un
    relabel que conserva la cantidad, auditado; lo hace el mismo operario en picking para poder
    liberar el despacho (ver ``inventory_service.correct_balance_lot``)."""
    task = await _load_task(tenant_id, task_id)
    _assert_can_operate(task, user)
    line = _line_or_404(task, line_id)
    balance = await inventory_service.correct_balance_lot(
        tenant_id=tenant_id,
        product_id=line["product_id"],
        warehouse_id=task["warehouse_id"],
        location_id=location_id,
        from_lot_number=from_lot_number,
        to_lot_number=to_lot_number,
        to_expiration_date=to_expiration_date,
        created_by=user.id,
        reason=f"Corrección de lote en picking (tarea {task_id})",
    )
    return {"line_id": line_id, "balance": serialize(balance)}


async def sync_lots(tenant_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Refresca la foto de lotes de Defontana (``erp_batches``) para ver el lote correcto. No
    mueve stock, así que la puede disparar el operario desde picking."""
    return await integration_service.run_sync_batches(tenant_id, user.id)


async def mark_missing(
    tenant_id: str, task_id: str, user: CurrentUser, sku: str, reason: str
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
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
    db = tenant_db(tenant_id)
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
    db = tenant_db(tenant_id)
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
            detail="Hay líneas pendientes. Confirmá el cierre parcial para continuar.",
        )

    # Trazabilidad del faltante: toda línea sin pickear (0) que no esté ya marcada como
    # faltante se auto-marca 'missing' con motivo, para que el corto quede auditable.
    for line in task["lines"]:
        if (line.get("quantity_picked", 0) == 0
                and line.get("status") != PickingLineStatus.MISSING.value):
            line["status"] = PickingLineStatus.MISSING.value
            line.setdefault("missing_reason", "Sin stock (cierre parcial)")

    warehouse_id = task["warehouse_id"]
    staging_id = await _location_id_by_type(tenant_id, warehouse_id, "staging")

    # Movimientos de pick auditables (los movimientos de piso nunca bloquean). Un movimiento por
    # (ubicación, lote): descuenta el lote que eligió el operario en cada scan y lo lleva a
    # staging con su vencimiento, para que el lote viaje hasta la guía de despacho.
    for line in task["lines"]:
        qty = line.get("quantity_picked", 0)
        if not (qty and qty > 0 and line.get("product_id")):
            continue
        groups: Dict[Any, Dict[str, Any]] = {}
        covered = 0.0
        for s in line.get("scans", []):
            sq = s.get("quantity", 0) or 0
            if sq <= 0:
                continue
            loc = s.get("location_id") or line.get("suggested_location_id")
            g = groups.setdefault((loc, s.get("lot_number")),
                                  {"qty": 0.0, "expiration": s.get("expiration_date")})
            g["qty"] += sq
            covered += sq
        # Residual sin scans (no debería pasar): sale de la ubicación sugerida, sin lote.
        if covered < qty:
            g = groups.setdefault((line.get("suggested_location_id"), None),
                                  {"qty": 0.0, "expiration": None})
            g["qty"] += qty - covered
        for (loc, lot), g in groups.items():
            await inventory_service.register_operational_move(
                tenant_id=tenant_id,
                movement_type=MovementType.PICK.value,
                product_id=line["product_id"],
                warehouse_id=warehouse_id,
                quantity=g["qty"],
                from_location_id=loc,
                to_location_id=staging_id,
                reference_type=ReferenceType.PICKING_TASK.value,
                reference_id=task_id,
                created_by=user.id,
                lot_number=lot,
                expiration_date=g["expiration"],
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
                "lines": task["lines"],
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
    # Reconciliar cantidades pickeadas + fulfillment en el pedido (fuente de verdad).
    await order_service.reconcile_order_from_picking(tenant_id, task["order_id"], task)

    # Section 8.2: packing becomes available once picking is closed.
    task = await _load_task(tenant_id, task_id)
    await packing_service.create_packing_task_from_picking(tenant_id, task, user)

    return serialize(task)


async def _current_picking_task(db, tenant_id: str, order_id: str) -> Optional[Dict[str, Any]]:
    """La tarea de picking vigente del pedido: la más reciente no cancelada. Con un pendiente
    (A.7) el pedido tiene más de una. Se ordena también por ``_id`` porque Mongo guarda las
    fechas al milisegundo y dos tareas del mismo milisegundo empatarían."""
    found = await (
        db[Collections.PICKING_TASKS]
        .find({"tenant_id": tenant_id, "order_id": order_id,
               "status": {"$ne": PickingTaskStatus.CANCELLED.value}})
        .sort([("created_at", -1), ("_id", -1)])
        .limit(1)
        .to_list(length=1)
    )
    return found[0] if found else None


async def reopen_picking(tenant_id: str, order_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Retroceso (supervisor): reabrir el picking. El pedido vuelve a 'picking', la tarea
    de picking a 'in_progress' y la de packing se cancela (se regenera al recompletar el
    picking). Ajuste automático: revierte los movimientos de inventario de packing y
    picking (la mercadería vuelve a su ubicación de origen); se re-aplican al recompletar."""
    db = tenant_db(tenant_id)
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

    # Pendiente en curso (segunda tarea de un pedido ya despachado en parte): se reabre SOLO
    # esa tarea. Revertir el packing de la guía anterior devolvería a staging mercadería que
    # ya salió, y poner lo despachado en cero borraría el registro de esa guía.
    current = await _current_picking_task(db, tenant_id, order_id)
    if current and current.get("is_backorder"):
        current_id = str(current["_id"])
        own_packing = await db[Collections.PACKING_TASKS].find(
            {"tenant_id": tenant_id, "order_id": order_id, "picking_task_id": current_id}
        ).to_list(length=20)
        for pt in own_packing:
            await inventory_service.reverse_moves_for_reference(
                tenant_id=tenant_id, reference_type=ReferenceType.PACKING_TASK.value,
                reference_id=str(pt["_id"]), created_by=user.id,
                reason="Reverso por reapertura de picking (pendiente)",
            )
        await db[Collections.PACKING_TASKS].update_many(
            {"tenant_id": tenant_id, "order_id": order_id, "picking_task_id": current_id,
             "status": {"$ne": PackingTaskStatus.CANCELLED.value}},
            {"$set": {"status": PackingTaskStatus.CANCELLED.value, "updated_at": now,
                      "updated_by": user.id}},
        )
        await inventory_service.reverse_moves_for_reference(
            tenant_id=tenant_id, reference_type=ReferenceType.PICKING_TASK.value,
            reference_id=current_id, created_by=user.id,
            reason="Reverso por reapertura de picking (pendiente)",
        )
        await db[Collections.PICKING_TASKS].update_one(
            {"_id": current["_id"]},
            {"$set": {"status": PickingTaskStatus.IN_PROGRESS.value, "completed_at": None,
                      "updated_at": now, "updated_by": user.id}},
        )
        await db[Collections.ORDERS].update_one(
            {"_id": order["_id"]},
            {"$set": {"status": OrderStatus.PICKING.value, "updated_at": now}},
        )
        await order_service.recompute_after_backorder_reopen(tenant_id, order_id)
        await replenishment_alert_service.release_for_order(tenant_id, order_id)
        return serialize(await _load_task(tenant_id, current_id))

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
    # Resetear cantidades reconciliadas (pickeado/empacado/despachado) para no dejar
    # cantidades fantasma; se re-reconcilian al recompletar.
    await order_service.reset_order_reconciliation(tenant_id, order_id, stage="picking")
    return serialize(await _load_task(tenant_id, str(task["_id"]))) if task else {"status": "reverted"}


async def resume_partial(tenant_id: str, order_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Completar faltante (operario): retoma un pedido que quedó PARCIAL cuando ya llegó
    stock para al menos una línea corta. Reabre su picking con el mismo ajuste de
    inventario que el retroceso del supervisor, deja las líneas cortas escaneables otra
    vez (re-sugiriendo ubicación si la actual no alcanza: el stock nuevo pudo entrar a
    otra) y asigna la tarea a quien lo retoma, para que escanee solo lo que falta."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    allowed = (replenishment_alert_service.RESUMABLE_STATUSES
               + replenishment_alert_service.BACKORDER_STATUSES)
    if (order.get("fulfillment") != OrderFulfillment.PARTIAL.value
            or order.get("status") not in allowed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este pedido no quedó parcial en una etapa que se pueda retomar.",
        )

    if order.get("status") in replenishment_alert_service.BACKORDER_STATUSES:
        # Ya se despachó todo lo que había (decisión A.7): el faltante sale en una tarea
        # NUEVA con solo lo pendiente, y después en otra guía. Lo despachado no se reabre.
        in_progress = await db[Collections.PICKING_TASKS].find_one(
            {"tenant_id": tenant_id, "order_id": order_id,
             "status": {"$in": [PickingTaskStatus.PENDING.value,
                                PickingTaskStatus.IN_PROGRESS.value,
                                PickingTaskStatus.PAUSED.value]}}
        )
        if in_progress:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya hay un pendiente en preparación para este pedido.",
            )
        last = await _current_picking_task(db, tenant_id, order_id)
        if last:
            user.assert_warehouse_allowed(last.get("warehouse_id"))
        if not await replenishment_alert_service.evaluate_completable(tenant_id, order_id=order_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aún no hay stock disponible para completar las líneas faltantes.",
            )
        backorder = await order_service.create_backorder_picking_task(tenant_id, order, user.id)
        await replenishment_alert_service.release_for_order(tenant_id, order_id)
        return backorder
    task = await db[Collections.PICKING_TASKS].find_one(
        {"tenant_id": tenant_id, "order_id": order_id,
         "status": {"$ne": PickingTaskStatus.CANCELLED.value}}
    )
    if not task:
        raise HTTPException(status_code=409, detail="El pedido no tiene tarea de picking.")
    user.assert_warehouse_allowed(task.get("warehouse_id"))
    if not await replenishment_alert_service.evaluate_completable(tenant_id, order_id=order_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aún no hay stock disponible para completar las líneas faltantes.",
        )

    await reopen_picking(tenant_id, order_id, user)

    task = await _load_task(tenant_id, str(task["_id"]))
    warehouse_id = task["warehouse_id"]
    for line in task["lines"]:
        picked = line.get("quantity_picked", 0) or 0
        required = line.get("quantity_required", 0) or 0
        if picked >= required:
            continue
        line["status"] = (PickingLineStatus.PARTIAL.value if picked > 0
                          else PickingLineStatus.PENDING.value)
        line.pop("missing_reason", None)
        product_id = line.get("product_id")
        if not product_id:
            continue
        current = line.get("suggested_location_id")
        balance = (
            await inventory_service.get_balance_doc(tenant_id, product_id, warehouse_id, current)
            if current else None
        )
        if (balance or {}).get("quantity_on_hand", 0) < required:
            line["suggested_location_id"] = (
                await order_service._suggested_location(tenant_id, product_id, warehouse_id)
                or current
            )

    await db[Collections.PICKING_TASKS].update_one(
        {"_id": task["_id"]},
        {"$set": {"lines": task["lines"], "assigned_to": user.id,
                  "updated_at": now_utc(), "updated_by": user.id}},
    )
    return serialize(await _load_task(tenant_id, str(task["_id"])))
