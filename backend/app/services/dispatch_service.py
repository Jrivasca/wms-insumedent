from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.dispatch import DispatchStatus
from app.models.inventory import MovementType, ReferenceType
from app.models.notification import NotificationType
from app.models.order import OrderStatus
from app.models.packing import PackingTaskStatus
from app.models.sync_job import SyncJobType
from app.services import inventory_service, notification_service, sync_job_service


async def list_dispatches(
    tenant_id: str, limit: int = 500, offset: int = 0
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.DISPATCHES].count_documents(query)
    cursor = (
        db[Collections.DISPATCHES].find(query).sort("created_at", -1).skip(offset).limit(limit)
    )
    items = [serialize(d) for d in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def get_dispatch(tenant_id: str, dispatch_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    doc = await db[Collections.DISPATCHES].find_one(
        {"_id": to_object_id(dispatch_id), "tenant_id": tenant_id}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    return serialize(doc)


async def _location_id_by_type(tenant_id: str, warehouse_id: Optional[str], loc_type: str) -> Optional[str]:
    if not warehouse_id:
        return None
    db = tenant_db(tenant_id)
    loc = await db[Collections.LOCATIONS].find_one(
        {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "type": loc_type}
    )
    return str(loc["_id"]) if loc else None


def _remaining_by_line(order_lines: List[Dict[str, Any]]) -> Dict[str, int]:
    """Por línea: lo empacado menos lo ya despachado (lo que aún se puede despachar)."""
    return {
        ol.get("line_id"): max(0, (ol.get("packed_quantity", 0) or 0) - (ol.get("dispatched_quantity", 0) or 0))
        for ol in order_lines
    }


async def _active_packing_task(tenant_id: str, order_id: str) -> Optional[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    return await db[Collections.PACKING_TASKS].find_one(
        {"tenant_id": tenant_id, "order_id": order_id,
         "status": {"$ne": PackingTaskStatus.CANCELLED.value}}
    )


async def confirm_dispatch(
    tenant_id: str,
    order_id: str,
    user: CurrentUser,
    carrier: Optional[str] = None,
    tracking_number: Optional[str] = None,
    guide_number: Optional[str] = None,
    package_ids: Optional[List[str]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Confirmar un despacho (total o PARCIAL) para un pedido listo o parcialmente
    despachado, y encolar el job de sync. Un pedido puede tener VARIAS guías: se
    despacha ``package_ids`` (bultos), ``lines`` (cantidades por SKU) o —si ambos son
    None— todo el remanente. El pedido queda ``dispatched`` cuando no queda remanente,
    o ``partially_dispatched`` si aún falta despachar."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") not in (
        OrderStatus.READY_TO_DISPATCH.value,
        OrderStatus.PARTIALLY_DISPATCHED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order must be ready_to_dispatch or partially_dispatched to confirm dispatch",
        )

    order_lines = order.get("lines", [])
    line_by_id = {ol.get("line_id"): ol for ol in order_lines}
    line_by_sku: Dict[str, Dict[str, Any]] = {}
    for ol in order_lines:
        line_by_sku.setdefault(ol.get("sku"), ol)
    remaining = _remaining_by_line(order_lines)
    if sum(remaining.values()) <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No queda nada por despachar en este pedido.",
        )

    packing_task = await _active_packing_task(tenant_id, order_id)
    warehouse_id = (packing_task or {}).get("warehouse_id") or order.get("warehouse_id")

    # --- Resolver qué despacha ESTA guía: {line_id: cantidad} ---
    target: Dict[str, int] = {}
    used_packages: List[str] = []
    if package_ids:
        by_pid = {p.get("package_id"): p for p in (packing_task or {}).get("packages", [])}
        for pid in package_ids:
            pkg = by_pid.get(pid)
            if not pkg:
                raise HTTPException(status_code=404, detail=f"Bulto {pid} no encontrado.")
            if pkg.get("dispatch_id"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"El bulto {pid} ya está asignado a otra guía.",
                )
            used_packages.append(pid)
            for it in pkg.get("items", []):
                ol = line_by_sku.get(it.get("sku"))
                if ol:
                    lid = ol.get("line_id")
                    target[lid] = target.get(lid, 0) + int(it.get("quantity") or 0)
    elif lines:
        for li in lines:
            ol = line_by_sku.get(li.get("sku"))
            qty = int(li.get("quantity") or 0)
            if ol and qty > 0:
                lid = ol.get("line_id")
                target[lid] = target.get(lid, 0) + qty
    else:
        target = {lid: q for lid, q in remaining.items() if q > 0}

    target = {lid: q for lid, q in target.items() if q > 0}
    if not target:
        raise HTTPException(status_code=400, detail="No se seleccionó nada para despachar.")
    for lid, q in target.items():
        if q > remaining.get(lid, 0):
            sku = line_by_id.get(lid, {}).get("sku")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No se puede despachar {q} de {sku}: quedan {remaining.get(lid, 0)}.",
            )

    now = now_utc()
    dispatch = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "erp_order_number": order.get("erp_order_number"),
        "status": DispatchStatus.PENDING.value,
        "dispatch_date": now,
        "guide_number": guide_number,
        "carrier": carrier,
        "tracking_number": tracking_number,
        "warehouse_id": warehouse_id,
        "lines": [
            {"line_id": lid, "product_id": line_by_id[lid].get("product_id"),
             "sku": line_by_id[lid].get("sku"), "quantity": q}
            for lid, q in target.items()
        ],
        "package_ids": used_packages,
        "erp_dispatch_response": None,
        "created_by": user.id,
        "updated_by": user.id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.DISPATCHES].insert_one(dispatch)
    dispatch["_id"] = result.inserted_id
    dispatch_id = str(dispatch["_id"])

    # Inventario: la mercadería sale de la ubicación de packing (referencia = despacho,
    # para poder revertir SOLO esta guía al anularla).
    packing_loc = await _location_id_by_type(tenant_id, warehouse_id, "packing")
    for dl in dispatch["lines"]:
        if dl["product_id"] and dl["quantity"] > 0 and warehouse_id:
            await inventory_service.register_operational_move(
                tenant_id=tenant_id,
                movement_type=MovementType.DISPATCH.value,
                product_id=dl["product_id"],
                warehouse_id=warehouse_id,
                quantity=dl["quantity"],
                from_location_id=packing_loc,
                to_location_id=None,
                reference_type=ReferenceType.DISPATCH.value,
                reference_id=dispatch_id,
                created_by=user.id,
            )

    # Acumular lo despachado en el pedido.
    for ol in order_lines:
        inc = target.get(ol.get("line_id"), 0)
        if inc:
            ol["dispatched_quantity"] = (ol.get("dispatched_quantity", 0) or 0) + inc

    # Estampar la guía en los bultos incluidos.
    if used_packages and packing_task:
        for pkg in packing_task.get("packages", []):
            if pkg.get("package_id") in used_packages:
                pkg["dispatch_id"] = dispatch_id
                pkg["guide_number"] = guide_number
        await db[Collections.PACKING_TASKS].update_one(
            {"_id": packing_task["_id"]},
            {"$set": {"packages": packing_task.get("packages", []), "updated_at": now}},
        )

    new_remaining = sum(_remaining_by_line(order_lines).values())
    new_status = (
        OrderStatus.DISPATCHED.value if new_remaining <= 0
        else OrderStatus.PARTIALLY_DISPATCHED.value
    )
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": order_lines, "status": new_status, "updated_at": now}},
    )

    # Encolar el job de sync al ERP (el push por-guía a Defontana con cantidades/folio es
    # un refinamiento futuro; hoy Defontana está diferido y el sync es mock/por nº de orden).
    job = await sync_job_service.enqueue(
        tenant_id=tenant_id,
        job_type=SyncJobType.DISPATCH_ORDER.value,
        payload={
            "dispatch_id": dispatch_id,
            "order_id": order_id,
            "erp_order_number": order.get("erp_order_number"),
        },
        created_by=user.id,
    )
    await db[Collections.DISPATCHES].update_one(
        {"_id": dispatch["_id"]}, {"$set": {"sync_job_id": job["id"]}}
    )

    parcial = new_status == OrderStatus.PARTIALLY_DISPATCHED.value
    await notification_service.emit(
        tenant_id=tenant_id,
        notification_type=NotificationType.ORDER_DISPATCHED.value,
        title=f"Pedido {order.get('erp_order_number')} "
        + ("despachado parcial" if parcial else "despachado"),
        body=(order.get("customer") or "Sin cliente")
        + (f" · guía {guide_number}" if guide_number else "")
        + (f" · {carrier}" if carrier else ""),
        entity_type="order",
        entity_id=order_id,
        metadata={"erp_order_number": order.get("erp_order_number"),
                  "guide_number": guide_number, "partial": parcial},
        actor_id=user.id,
    )
    return serialize(await db[Collections.DISPATCHES].find_one({"_id": dispatch["_id"]}))


async def _revert_dispatch_effects(
    tenant_id: str, dispatch: Dict[str, Any], order_lines: List[Dict[str, Any]], user: CurrentUser
) -> None:
    """Revierte el inventario de UN despacho, resta lo despachado de las líneas del pedido
    y libera sus bultos. Muta ``order_lines`` in-place; el estado del pedido lo fija quien llama."""
    dispatch_id = str(dispatch["_id"])
    await inventory_service.reverse_moves_for_reference(
        tenant_id=tenant_id, reference_type=ReferenceType.DISPATCH.value,
        reference_id=dispatch_id, created_by=user.id, reason="Reverso por anulación de despacho",
    )
    by_id = {ol.get("line_id"): ol for ol in order_lines}
    for dl in dispatch.get("lines", []):
        ol = by_id.get(dl.get("line_id"))
        if ol:
            ol["dispatched_quantity"] = max(
                0, (ol.get("dispatched_quantity", 0) or 0) - int(dl.get("quantity") or 0)
            )
    # Liberar los bultos de esta guía.
    db = tenant_db(tenant_id)
    packing_task = await _active_packing_task(tenant_id, dispatch.get("order_id"))
    if packing_task:
        changed = False
        for pkg in packing_task.get("packages", []):
            if pkg.get("dispatch_id") == dispatch_id:
                pkg.pop("dispatch_id", None)
                pkg.pop("guide_number", None)
                changed = True
        if changed:
            await db[Collections.PACKING_TASKS].update_one(
                {"_id": packing_task["_id"]},
                {"$set": {"packages": packing_task.get("packages", []), "updated_at": now_utc()}},
            )


async def cancel_dispatch(tenant_id: str, order_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Retroceso: anular TODAS las guías activas de un pedido (des)pachado. El pedido
    vuelve a 'ready_to_dispatch', el inventario de despacho se revierte y las guías quedan
    'cancelled' (puede re-despacharse). Para anular UNA sola guía, ver ``cancel_dispatch_by_id``."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.get("status") not in (
        OrderStatus.DISPATCHED.value,
        OrderStatus.PARTIALLY_DISPATCHED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede anular el despacho de un pedido despachado.",
        )

    now = now_utc()
    order_lines = order.get("lines", [])
    dispatches = await db[Collections.DISPATCHES].find(
        {"tenant_id": tenant_id, "order_id": order_id,
         "status": {"$nin": [DispatchStatus.ERROR.value, DispatchStatus.CANCELLED.value]}}
    ).to_list(length=200)
    for d in dispatches:
        await _revert_dispatch_effects(tenant_id, d, order_lines, user)
        await db[Collections.DISPATCHES].update_one(
            {"_id": d["_id"]},
            {"$set": {"status": DispatchStatus.CANCELLED.value, "updated_at": now,
                      "updated_by": user.id}},
        )
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": order_lines, "status": OrderStatus.READY_TO_DISPATCH.value,
                  "updated_at": now}},
    )
    return {"status": "reverted", "cancelled": len(dispatches)}


async def cancel_dispatch_by_id(tenant_id: str, dispatch_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Anular UNA guía: revierte su inventario, resta lo despachado y recomputa el estado
    del pedido (partially_dispatched si quedan otras guías, si no ready_to_dispatch)."""
    db = tenant_db(tenant_id)
    dispatch = await db[Collections.DISPATCHES].find_one(
        {"_id": to_object_id(dispatch_id), "tenant_id": tenant_id}
    )
    if not dispatch:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    if dispatch.get("status") in (DispatchStatus.CANCELLED.value, DispatchStatus.ERROR.value):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El despacho ya está anulado.")

    now = now_utc()
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(dispatch.get("order_id")), "tenant_id": tenant_id}
    )
    order_lines = order.get("lines", []) if order else []
    await _revert_dispatch_effects(tenant_id, dispatch, order_lines, user)
    await db[Collections.DISPATCHES].update_one(
        {"_id": dispatch["_id"]},
        {"$set": {"status": DispatchStatus.CANCELLED.value, "updated_at": now, "updated_by": user.id}},
    )
    if order:
        total_dispatched = sum((ol.get("dispatched_quantity", 0) or 0) for ol in order_lines)
        new_status = (
            OrderStatus.PARTIALLY_DISPATCHED.value if total_dispatched > 0
            else OrderStatus.READY_TO_DISPATCH.value
        )
        await db[Collections.ORDERS].update_one(
            {"_id": order["_id"]},
            {"$set": {"lines": order_lines, "status": new_status, "updated_at": now}},
        )
    return await get_dispatch(tenant_id, dispatch_id)


async def list_order_dispatches(tenant_id: str, order_id: str) -> Dict[str, Any]:
    """Todas las guías (despachos) de un pedido, más recientes primero."""
    db = tenant_db(tenant_id)
    query = {"tenant_id": tenant_id, "order_id": order_id}
    total = await db[Collections.DISPATCHES].count_documents(query)
    cursor = db[Collections.DISPATCHES].find(query).sort("created_at", -1)
    items = [serialize(d) for d in await cursor.to_list(length=500)]
    return page(items, total, 500, 0)
