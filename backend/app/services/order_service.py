from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.location import NON_PICKABLE_LOCATION_TYPES
from app.models.order import OrderFulfillment, OrderLineStatus, OrderStatus
from app.models.packing import PackingTaskStatus
from app.models.picking import PickingLineStatus, PickingTaskStatus
from app.models.notification import NotificationType
from app.models.sync_job import SyncJobType
from app.services import notification_service, replenishment_alert_service, sync_job_service


async def _expected_barcodes(tenant_id: str, product_id: str, sku: str) -> List[str]:
    db = tenant_db(tenant_id)
    codes = [
        b["barcode"]
        async for b in db[Collections.BARCODES].find(
            {"tenant_id": tenant_id, "product_id": product_id, "is_active": True}
        )
    ]
    if sku:
        codes.append(sku)
    return codes


async def _suggested_location(
    tenant_id: str, product_id: str, warehouse_id: str
) -> Optional[str]:
    db = tenant_db(tenant_id)
    # Nunca sugerir stock no pickeable: lo que está en staging, packing o despacho ya es de
    # otro pedido, cuarentena está bloqueada y recepción todavía no se guardó en un estante.
    # Antes se sugería cualquier ubicación con stock, así que FEFO podía mandar a un operario
    # a sacar mercadería que estaba en preparación para otro pedido.
    excluded = [
        str(location["_id"])
        async for location in db[Collections.LOCATIONS].find(
            {
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
                "type": {"$in": list(NON_PICKABLE_LOCATION_TYPES)},
            },
            {"_id": 1},
        )
    ]
    # FEFO (Fase 5): prefer the lot with the nearest expiration among those with stock.
    fefo = (
        await db[Collections.INVENTORY_BALANCES]
        .find(
            {
                "tenant_id": tenant_id,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "location_id": {"$nin": excluded},
                "quantity_on_hand": {"$gt": 0},
                "expiration_date": {"$ne": None},
            }
        )
        .sort([("expiration_date", 1)])
        .to_list(length=1)
    )
    if fefo:
        return fefo[0]["location_id"]
    # Otherwise any pickable location that already holds stock for this product.
    balance = await db[Collections.INVENTORY_BALANCES].find_one(
        {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "location_id": {"$nin": excluded},
            "quantity_on_hand": {"$gt": 0},
        }
    )
    if balance:
        return balance["location_id"]
    # Fall back to the first storage/picking location of the warehouse.
    location = await db[Collections.LOCATIONS].find_one(
        {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "type": {"$in": ["storage", "picking"]},
        }
    )
    return str(location["_id"]) if location else None


async def _default_warehouse_id(tenant_id: str) -> Optional[str]:
    db = tenant_db(tenant_id)
    warehouse = await db[Collections.WAREHOUSES].find_one(
        {"tenant_id": tenant_id, "is_active": True}
    )
    return str(warehouse["_id"]) if warehouse else None


async def list_orders(
    tenant_id: str,
    status_filter: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status_filter:
        query["status"] = status_filter
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.ORDERS].count_documents(query)
    cursor = (
        db[Collections.ORDERS].find(query).sort("created_at", -1).skip(offset).limit(limit)
    )
    items = [serialize(o) for o in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def get_order(tenant_id: str, order_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize(order)


async def create_order_from_lines(
    *,
    tenant_id: str,
    erp_order_number: str,
    customer: Optional[str],
    lines: Any,
    created_by: str,
    source_document: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an order (status ``imported``) and enqueue the ERP push.

    Shared by the manual ``POST /orders`` route and the PDF import flow. ``lines``
    is any iterable of objects exposing ``sku``/``name``/``unit``/``ordered_quantity``
    and optionally ``product_id`` (already resolved by the import review screen).
    Products are matched by ``product_id`` when given, else by exact SKU; a line with
    no catalog match is kept (``product_id=None``), mirroring the manual behavior.
    """
    db = tenant_db(tenant_id)
    existing = await db[Collections.ORDERS].find_one(
        {"tenant_id": tenant_id, "erp_order_number": erp_order_number}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Order number already exists")

    built = []
    for idx, line in enumerate(lines, start=1):
        sku = (getattr(line, "sku", None) or "").strip()
        pid = getattr(line, "product_id", None)
        product = None
        if pid:
            product = await db[Collections.PRODUCTS].find_one(
                {"_id": to_object_id(pid), "tenant_id": tenant_id}
            )
        if product is None and sku:
            product = await db[Collections.PRODUCTS].find_one(
                {"tenant_id": tenant_id, "sku": sku}
            )
        name = getattr(line, "name", None)
        built.append(
            {
                "line_id": f"L{idx}",
                "product_id": str(product["_id"]) if product else None,
                "sku": sku or (product.get("sku") if product else ""),
                "name": name or (product.get("name") if product else sku),
                "unit": getattr(line, "unit", None) or "UN",
                "ordered_quantity": getattr(line, "ordered_quantity"),
                "picked_quantity": 0,
                "packed_quantity": 0,
                "dispatched_quantity": 0,
                "status": OrderLineStatus.PENDING.value,
            }
        )

    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "erp_order_number": erp_order_number,
        "erp_document_id": None,
        "customer": customer,
        "status": OrderStatus.IMPORTED.value,
        "fulfillment": OrderFulfillment.COMPLETE.value,
        "order_date": now,
        "delivery_date": None,
        "lines": built,
        "raw_erp_data": None,
        "source_document": source_document,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": created_by,
    }
    result = await db[Collections.ORDERS].insert_one(doc)
    doc["_id"] = result.inserted_id

    # Enqueue ERP sync (push the order to Defontana). Best-effort + async.
    # En operación stand-alone (ERP_SYNC_ENABLED=false) no se encola nada, igual
    # que en la creación manual de pedidos.
    if settings.erp_sync_enabled:
        await sync_job_service.enqueue(
            tenant_id=tenant_id,
            job_type=SyncJobType.CREATE_ORDER.value,
            payload={
                "order_id": str(doc["_id"]),
                "Number": erp_order_number,
                "Client": {"Name": customer},
                "Detail": [
                    {"Code": ln["sku"], "Name": ln["name"], "Unit": ln["unit"], "Quantity": ln["ordered_quantity"]}
                    for ln in built
                ],
            },
            created_by=created_by,
        )

    await notification_service.emit(
        tenant_id=tenant_id,
        notification_type=NotificationType.ORDER_CREATED.value,
        title=f"Nuevo pedido {erp_order_number}",
        body=f"{customer or 'Sin cliente'} · {len(built)} línea(s)",
        entity_type="order",
        entity_id=str(doc["_id"]),
        metadata={"erp_order_number": erp_order_number},
        actor_id=created_by,
    )
    return serialize(doc)


async def _picking_line(
    tenant_id: str, line: Dict[str, Any], warehouse_id: str, quantity: float
) -> Dict[str, Any]:
    """Línea de una tarea de picking a partir de una línea del pedido. La comparten la tarea
    normal (pide todo lo pedido) y la del pendiente (pide solo lo que falta)."""
    product_id = line.get("product_id")
    sku = line.get("sku", "")
    expected = await _expected_barcodes(tenant_id, product_id, sku) if product_id else [sku]
    suggested = (
        await _suggested_location(tenant_id, product_id, warehouse_id)
        if product_id
        else None
    )
    return {
        "line_id": line.get("line_id"),
        "product_id": product_id,
        "sku": sku,
        "name": line.get("name"),
        "unit": line.get("unit", "UN"),
        "barcode_expected": expected,
        "quantity_required": quantity,
        "quantity_picked": 0,
        "suggested_location_id": suggested,
        "scans": [],
        "status": PickingLineStatus.PENDING.value,
    }


async def create_picking_task(
    tenant_id: str, order_id: str, created_by: str
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Only an order that has not yet been picked can generate a (new) picking task.
    # Once it reaches picked/packing/…/dispatched the flow has moved on, so a second
    # "Generar picking" must be refused (it previously only blocked dispatched/cancelled).
    if order.get("status") not in (
        OrderStatus.IMPORTED.value,
        OrderStatus.PENDING_PICKING.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El pedido ya está en '{order.get('status')}'; "
                "no se puede generar picking nuevamente."
            ),
        )

    existing = await db[Collections.PICKING_TASKS].find_one(
        {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": {"$nin": [PickingTaskStatus.CANCELLED.value]},
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A picking task already exists for this order",
        )

    warehouse_id = order.get("warehouse_id") or await _default_warehouse_id(tenant_id)
    if not warehouse_id:
        raise HTTPException(status_code=400, detail="No warehouse available for picking")

    lines = [
        await _picking_line(tenant_id, line, warehouse_id, line.get("ordered_quantity", 0))
        for line in order.get("lines", [])
    ]

    now = now_utc()
    task = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "erp_order_number": order.get("erp_order_number"),
        "assigned_to": created_by,
        "warehouse_id": warehouse_id,
        "status": PickingTaskStatus.PENDING.value,
        "started_at": None,
        "completed_at": None,
        "lines": lines,
        "created_by": created_by,
        "updated_by": created_by,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.PICKING_TASKS].insert_one(task)
    task["_id"] = result.inserted_id

    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"status": OrderStatus.PENDING_PICKING.value, "updated_at": now}},
    )
    return serialize(task)


# ---------------------------------------------------------------------------
# Reconciliación pedido ↔ tareas (Plan: fulfillment parcial)
# ---------------------------------------------------------------------------
# El documento del pedido es la fuente de verdad de cantidades. Estas funciones
# copian lo realmente pickeado/empacado de la tarea a ``order.lines[]`` (matcheando
# por ``line_id``) y derivan el estado de línea + el ``fulfillment`` del pedido.


def _line_status_for(qty: int, ordered: int, full_status: str) -> str:
    """Estado de la línea del pedido según la cantidad cumplida vs. la pedida."""
    if ordered > 0 and qty >= ordered:
        return full_status
    if qty > 0:
        return OrderLineStatus.PARTIAL.value
    return OrderLineStatus.MISSING.value


def compute_fulfillment(lines: List[Dict[str, Any]]) -> str:
    """``partial`` si alguna línea quedó corta (pickeado < pedido); si no ``complete``."""
    for line in lines:
        if line.get("picked_quantity", 0) < line.get("ordered_quantity", 0):
            return OrderFulfillment.PARTIAL.value
    return OrderFulfillment.COMPLETE.value


# Tareas cerradas: las que cuentan para las cantidades del pedido.
_DONE_PICKING = (
    PickingTaskStatus.COMPLETED.value,
    PickingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
)
_DONE_PACKING = (PackingTaskStatus.COMPLETED.value,)


async def _task_totals(
    db, tenant_id: str, collection: str, order_id: str, statuses, field: str
) -> Dict[str, float]:
    """Suma por línea de ``field`` en las tareas del pedido con estado en ``statuses``.

    Un pedido puede tener más de una tarea: el pendiente de un pedido parcial sale en una
    tarea nueva (decisión A.7). Lo pickeado y lo empacado del pedido es la suma de todas;
    con una sola tarea, el resultado es el mismo de antes."""
    totals: Dict[str, float] = {}
    async for task in db[collection].find(
        {"tenant_id": tenant_id, "order_id": order_id, "status": {"$in": list(statuses)}}
    ):
        for line in task.get("lines", []):
            line_id = line.get("line_id")
            totals[line_id] = totals.get(line_id, 0) + (line.get(field, 0) or 0)
    return totals


def _fefo_key(expiration):
    """Orden FEFO: primero el que vence antes; los sin fecha, al final."""
    return (expiration is None, expiration or datetime.max)


async def _picked_lots_by_line(
    db, tenant_id: str, order_id: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Desglose de lote por línea de lo pickeado del pedido: agrupa los scans de todas las
    tareas de picking cerradas por (lote, vencimiento) y suma cantidades, ordenado FEFO. Es
    la fuente para poblar los lotes de la guía (``BatchInfo`` de ``Dispatch/Save``): el lote
    lo eligió el operario al pickear (Parte 1) y acá viaja hasta el pedido."""
    by_line: Dict[str, Dict[Any, Dict[str, Any]]] = {}
    async for task in db[Collections.PICKING_TASKS].find(
        {"tenant_id": tenant_id, "order_id": order_id, "status": {"$in": list(_DONE_PICKING)}}
    ):
        for line in task.get("lines", []):
            groups = by_line.setdefault(line.get("line_id"), {})
            for s in line.get("scans", []):
                qty = s.get("quantity", 0) or 0
                if qty <= 0 or not s.get("lot_number"):
                    continue
                exp = s.get("expiration_date")
                g = groups.setdefault(
                    (s.get("lot_number"), exp),
                    {"lot_number": s.get("lot_number"), "expiration_date": exp, "quantity": 0.0},
                )
                g["quantity"] += qty
    return {
        line_id: sorted(groups.values(), key=lambda g: _fefo_key(g["expiration_date"]))
        for line_id, groups in by_line.items()
    }


async def reconcile_order_from_picking(
    tenant_id: str, order_id: str, picking_task: Dict[str, Any]
) -> None:
    """Lo pickeado del pedido es la suma de sus tareas de picking cerradas. ``picking_task``
    se conserva por compatibilidad: las cantidades se leen de la base, donde quien llama ya
    dejó la tarea cerrada."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        return
    picked_by_line = await _task_totals(
        db, tenant_id, Collections.PICKING_TASKS, order_id, _DONE_PICKING, "quantity_picked"
    )
    lots_by_line = await _picked_lots_by_line(db, tenant_id, order_id)
    lines = order.get("lines", [])
    for ol in lines:
        picked = picked_by_line.get(ol.get("line_id"))
        if picked is None:
            continue
        ol["picked_quantity"] = picked
        # Desglose de lote de lo pickeado (para la guía). Solo para líneas con lote elegido.
        ol["picked_lots"] = lots_by_line.get(ol.get("line_id"), [])
        ol["status"] = _line_status_for(picked, ol.get("ordered_quantity", 0),
                                        OrderLineStatus.PICKED.value)
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": lines, "fulfillment": compute_fulfillment(lines),
                  "updated_at": now_utc()}},
    )


async def reconcile_order_from_packing(
    tenant_id: str, order_id: str, packing_task: Dict[str, Any]
) -> None:
    """Lo empacado del pedido es la suma de sus tareas de packing cerradas (ver
    ``reconcile_order_from_picking``)."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        return
    packed_by_line = await _task_totals(
        db, tenant_id, Collections.PACKING_TASKS, order_id, _DONE_PACKING, "quantity_packed"
    )
    lines = order.get("lines", [])
    for ol in lines:
        packed = packed_by_line.get(ol.get("line_id"))
        if packed is None:
            continue  # línea faltante (no llegó a packing): conserva su estado del picking
        ol["packed_quantity"] = packed
        ol["status"] = _line_status_for(packed, ol.get("ordered_quantity", 0),
                                        OrderLineStatus.PACKED.value)
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": lines, "fulfillment": compute_fulfillment(lines),
                  "updated_at": now_utc()}},
    )


async def reset_order_reconciliation(
    tenant_id: str, order_id: str, *, stage: str
) -> None:
    """Retroceso: al reabrir picking/packing, resetear las cantidades reconciliadas de
    ``order.lines`` para no dejar cantidades fantasma. ``stage='picking'`` resetea
    pickeado+empacado+despachado (vuelve todo a pendiente); ``stage='packing'`` resetea
    solo lo empacado (el picking se conserva)."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        return
    lines = order.get("lines", [])
    for ol in lines:
        ol["packed_quantity"] = 0
        if stage == "picking":
            ol["picked_quantity"] = 0
            ol["dispatched_quantity"] = 0
            # El desglose de lote se re-deriva al recompletar el picking; limpiarlo para no
            # dejar lotes fantasma de la corrida anterior.
            ol["picked_lots"] = []
            ol["dispatched_lots"] = []
            ol["status"] = OrderLineStatus.PENDING.value
        else:  # packing: el pickeado se mantiene, se re-deriva el estado
            ol["status"] = _line_status_for(ol.get("picked_quantity", 0),
                                            ol.get("ordered_quantity", 0),
                                            OrderLineStatus.PICKED.value)
    # Al reabrir el picking el pedido vuelve a 'pending' → el fulfillment se desconoce
    # otra vez (complete por defecto); al reabrir solo packing, el picking sigue válido.
    fulfillment = (OrderFulfillment.COMPLETE.value if stage == "picking"
                   else compute_fulfillment(lines))
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": lines, "fulfillment": fulfillment, "updated_at": now_utc()}},
    )
    if stage == "picking":
        # El pedido se retomó: un nuevo faltante al recompletar debe volver a avisar.
        await replenishment_alert_service.release_for_order(tenant_id, order_id)


# ---------------------------------------------------------------------------
# Pendiente de un pedido parcial ya despachado (decisión A.7)
# ---------------------------------------------------------------------------
# Se despacha lo que hay y lo que falta sale después en otra guía. El pendiente es una
# tarea de picking NUEVA con solo lo que falta; lo ya despachado nunca se toca.


async def recompute_after_backorder_reopen(tenant_id: str, order_id: str) -> None:
    """Retroceso de un pendiente: las cantidades del pedido se recalculan desde las tareas
    que siguen cerradas, en vez de ponerse en cero como en un pedido de una sola tarea. Lo
    que salió en la guía anterior (pickeado, empacado y despachado) se conserva; solo se
    descuenta el aporte de la tarea que se reabrió."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        return
    picked = await _task_totals(
        db, tenant_id, Collections.PICKING_TASKS, order_id, _DONE_PICKING, "quantity_picked"
    )
    packed = await _task_totals(
        db, tenant_id, Collections.PACKING_TASKS, order_id, _DONE_PACKING, "quantity_packed"
    )
    lines = order.get("lines", [])
    for ol in lines:
        line_id = ol.get("line_id")
        ordered = ol.get("ordered_quantity", 0)
        ol["picked_quantity"] = picked.get(line_id, 0)
        ol["packed_quantity"] = packed.get(line_id, 0)
        # dispatched_quantity no se toca: esa mercadería ya salió.
        if ol["packed_quantity"] > 0:
            ol["status"] = _line_status_for(ol["packed_quantity"], ordered,
                                            OrderLineStatus.PACKED.value)
        else:
            ol["status"] = _line_status_for(ol["picked_quantity"], ordered,
                                            OrderLineStatus.PICKED.value)
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"lines": lines, "fulfillment": compute_fulfillment(lines),
                  "updated_at": now_utc()}},
    )


async def create_backorder_picking_task(
    tenant_id: str, order: Dict[str, Any], created_by: str
) -> Dict[str, Any]:
    """Tarea de picking con SOLO lo que falta de un pedido ya despachado en parte: por
    línea, lo pedido menos lo pickeado. Queda asignada a quien la crea y marcada como
    pendiente (``is_backorder``), con su número correlativo entre las tareas del pedido."""
    db = tenant_db(tenant_id)
    order_id = str(order["_id"])
    previous = await (
        db[Collections.PICKING_TASKS]
        .find({"tenant_id": tenant_id, "order_id": order_id,
               "status": {"$ne": PickingTaskStatus.CANCELLED.value}})
        .sort("created_at", -1)
        .to_list(length=50)
    )
    warehouse_id = (
        (previous[0].get("warehouse_id") if previous else None)
        or order.get("warehouse_id")
        or await _default_warehouse_id(tenant_id)
    )
    if not warehouse_id:
        raise HTTPException(status_code=400, detail="No warehouse available for picking")

    lines = []
    for line in order.get("lines", []):
        shortfall = (line.get("ordered_quantity", 0) or 0) - (line.get("picked_quantity", 0) or 0)
        if line.get("product_id") and shortfall > 0:
            lines.append(await _picking_line(tenant_id, line, warehouse_id, shortfall))
    if not lines:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El pedido no tiene líneas pendientes.",
        )

    now = now_utc()
    task = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "erp_order_number": order.get("erp_order_number"),
        "assigned_to": created_by,
        "warehouse_id": warehouse_id,
        "status": PickingTaskStatus.PENDING.value,
        "started_at": None,
        "completed_at": None,
        "lines": lines,
        "is_backorder": True,
        "sequence": len(previous) + 1,
        "created_by": created_by,
        "updated_by": created_by,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.PICKING_TASKS].insert_one(task)
    task["_id"] = result.inserted_id
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"status": OrderStatus.PENDING_PICKING.value, "updated_at": now}},
    )
    return serialize(task)
