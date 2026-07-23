from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.order import OrderLineStatus, OrderStatus
from app.models.picking import PickingLineStatus, PickingTaskStatus
from app.models.sync_job import SyncJobType
from app.services import sync_job_service


async def _expected_barcodes(tenant_id: str, product_id: str, sku: str) -> List[str]:
    db = get_database()
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
    db = get_database()
    # Prefer a location that already holds stock for this product.
    balance = await db[Collections.INVENTORY_BALANCES].find_one(
        {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
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
    db = get_database()
    warehouse = await db[Collections.WAREHOUSES].find_one(
        {"tenant_id": tenant_id, "is_active": True}
    )
    return str(warehouse["_id"]) if warehouse else None


async def list_orders(tenant_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status_filter:
        query["status"] = status_filter
    cursor = db[Collections.ORDERS].find(query).sort("created_at", -1)
    return [serialize(o) for o in await cursor.to_list(length=500)]


async def get_order(tenant_id: str, order_id: str) -> Dict[str, Any]:
    db = get_database()
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
    db = get_database()
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
    return serialize(doc)


async def create_picking_task(
    tenant_id: str, order_id: str, created_by: str
) -> Dict[str, Any]:
    db = get_database()
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.get("status") in (
        OrderStatus.DISPATCHED.value,
        OrderStatus.CANCELLED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot create picking for order in status '{order.get('status')}'",
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

    lines = []
    for line in order.get("lines", []):
        product_id = line.get("product_id")
        sku = line.get("sku", "")
        expected = await _expected_barcodes(tenant_id, product_id, sku) if product_id else [sku]
        suggested = (
            await _suggested_location(tenant_id, product_id, warehouse_id)
            if product_id
            else None
        )
        lines.append(
            {
                "line_id": line.get("line_id"),
                "product_id": product_id,
                "sku": sku,
                "name": line.get("name"),
                "unit": line.get("unit", "UN"),
                "barcode_expected": expected,
                "quantity_required": line.get("ordered_quantity", 0),
                "quantity_picked": 0,
                "suggested_location_id": suggested,
                "scans": [],
                "status": PickingLineStatus.PENDING.value,
            }
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
