"""Inventory engine.

Golden rule (section 8.4): stock is never modified without recording a movement.
All public mutators in this module both update ``inventory_balances`` and append a
document to ``inventory_movements``.
"""
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.sync_job import SyncJobType
from app.services import sync_job_service


def _available(balance: Dict[str, Any]) -> float:
    return (
        balance.get("quantity_on_hand", 0)
        - balance.get("quantity_reserved", 0)
        - balance.get("quantity_blocked", 0)
    )


async def get_balance_doc(
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    location_id: str,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    return await db[Collections.INVENTORY_BALANCES].find_one(
        {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "location_id": location_id,
            "lot_number": lot_number,
            "serial_number": serial_number,
        }
    )


async def change_location_stock(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    location_id: str,
    delta: float,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    allow_negative: bool = False,
) -> Dict[str, Any]:
    """Apply ``delta`` to on-hand stock of a single location and return the balance.

    Does NOT record a movement on its own; callers must pair it with
    :func:`record_movement` (see the higher-level helpers below).
    """
    db = tenant_db(tenant_id)
    key = {
        "tenant_id": tenant_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "location_id": location_id,
        "lot_number": lot_number,
        "serial_number": serial_number,
    }
    balance = await db[Collections.INVENTORY_BALANCES].find_one(key)
    current = balance.get("quantity_on_hand", 0) if balance else 0
    new_on_hand = current + delta

    if new_on_hand < 0 and not (allow_negative or settings.allow_negative_stock):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operation would produce negative stock",
        )

    reserved = balance.get("quantity_reserved", 0) if balance else 0
    blocked = balance.get("quantity_blocked", 0) if balance else 0
    doc = {
        **key,
        "quantity_on_hand": new_on_hand,
        "quantity_reserved": reserved,
        "quantity_blocked": blocked,
        "quantity_available": new_on_hand - reserved - blocked,
        "updated_at": now_utc(),
    }
    await db[Collections.INVENTORY_BALANCES].update_one(key, {"$set": doc}, upsert=True)
    return await db[Collections.INVENTORY_BALANCES].find_one(key)


async def record_movement(
    *,
    tenant_id: str,
    movement_type: str,
    product_id: str,
    warehouse_id: str,
    quantity: float,
    from_location_id: Optional[str] = None,
    to_location_id: Optional[str] = None,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    reason: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    doc = {
        "tenant_id": tenant_id,
        "movement_type": movement_type,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "quantity": quantity,
        "lot_number": lot_number,
        "serial_number": serial_number,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "reason": reason,
        "created_by": created_by,
        "created_at": now_utc(),
    }
    result = await db[Collections.INVENTORY_MOVEMENTS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------
async def create_adjustment(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    location_id: str,
    quantity: float,
    reason: str,
    created_by: str,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Supervisor-approved stock adjustment. ``quantity`` may be negative."""
    balance = await change_location_stock(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        delta=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
    )
    await record_movement(
        tenant_id=tenant_id,
        movement_type=MovementType.ADJUSTMENT.value,
        product_id=product_id,
        warehouse_id=warehouse_id,
        to_location_id=location_id if quantity >= 0 else None,
        from_location_id=location_id if quantity < 0 else None,
        quantity=abs(quantity),
        lot_number=lot_number,
        serial_number=serial_number,
        reference_type=ReferenceType.MANUAL.value,
        reason=reason,
        created_by=created_by,
    )
    return balance


async def create_transfer(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    from_location_id: str,
    to_location_id: str,
    quantity: float,
    created_by: str,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
) -> Dict[str, Any]:
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Transfer quantity must be positive")

    await change_location_stock(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=from_location_id,
        delta=-quantity,
        lot_number=lot_number,
        serial_number=serial_number,
    )
    await change_location_stock(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=to_location_id,
        delta=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
        allow_negative=True,
    )
    movement = await record_movement(
        tenant_id=tenant_id,
        movement_type=MovementType.TRANSFER.value,
        product_id=product_id,
        warehouse_id=warehouse_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
        reference_type=ReferenceType.MANUAL.value,
        created_by=created_by,
    )
    return movement


async def create_reception(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    location_id: str,
    quantity: float,
    created_by: str,
    reference: Optional[str] = None,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    sync_erp: bool = True,
) -> Dict[str, Any]:
    """Receive inbound stock into a location (entrada de mercadería).

    Adds stock + records a RECEIPT movement, and (optionally) enqueues an ERP
    inventory-entry document (Defontana ``PUT /Inventory/Insert``, real-supported).
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser positiva")

    balance = await change_location_stock(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        delta=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
        allow_negative=True,
    )
    movement = await record_movement(
        tenant_id=tenant_id,
        movement_type=MovementType.RECEIPT.value,
        product_id=product_id,
        warehouse_id=warehouse_id,
        to_location_id=location_id,
        quantity=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
        reference_type=ReferenceType.MANUAL.value,
        reference_id=reference,
        reason="Recepción de mercadería",
        created_by=created_by,
    )

    job = None
    if sync_erp and settings.erp_sync_enabled:
        db = tenant_db(tenant_id)
        product = await db[Collections.PRODUCTS].find_one(
            {"_id": to_object_id(product_id), "tenant_id": tenant_id}
        )
        warehouse = await db[Collections.WAREHOUSES].find_one(
            {"_id": to_object_id(warehouse_id), "tenant_id": tenant_id}
        )
        payload = {
            "externalDocumentID": f"WMS-REC-{movement['_id']}",
            "storageCode": (warehouse or {}).get("erp_storage_code"),
            "type": "entrada",
            "detail": [
                {
                    "code": (product or {}).get("sku"),
                    "quantity": quantity,
                    "lotNumber": lot_number,
                    "serialNumber": serial_number,
                }
            ],
        }
        job = await sync_job_service.enqueue(
            tenant_id=tenant_id,
            job_type=SyncJobType.CREATE_INVENTORY_DOCUMENT.value,
            payload=payload,
            created_by=created_by,
        )

    return {
        "balance": serialize(balance) if balance else None,
        "movement": serialize(movement),
        "sync_job_id": job["id"] if job else None,
    }


async def register_operational_move(
    *,
    tenant_id: str,
    movement_type: str,
    product_id: str,
    warehouse_id: str,
    quantity: float,
    from_location_id: Optional[str],
    to_location_id: Optional[str],
    reference_type: str,
    reference_id: str,
    created_by: str,
) -> None:
    """Stock move triggered by picking/packing/dispatch.

    Operational floor moves never block the operation, so they are recorded with
    ``allow_negative=True`` while still being fully traceable via the movement.
    """
    if from_location_id:
        await change_location_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=from_location_id,
            delta=-quantity,
            allow_negative=True,
        )
    if to_location_id:
        await change_location_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=to_location_id,
            delta=quantity,
            allow_negative=True,
        )
    await record_movement(
        tenant_id=tenant_id,
        movement_type=movement_type,
        product_id=product_id,
        warehouse_id=warehouse_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )


async def reverse_moves_for_reference(
    *, tenant_id: str, reference_type: str, reference_id: str, created_by: str, reason: str
) -> int:
    """Deshace los movimientos operativos de una referencia (una tarea de picking o
    packing): por cada movimiento crea el inverso (origen/destino intercambiados) para
    dejar los saldos como antes, lo registra como movimiento de reverso (auditable) y
    marca el original como revertido. Idempotente: no revierte dos veces el mismo
    movimiento. Devuelve cuántos movimientos revirtió."""
    db = tenant_db(tenant_id)
    moves = await db[Collections.INVENTORY_MOVEMENTS].find(
        {
            "tenant_id": tenant_id,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "reversed": {"$ne": True},
            "is_reversal": {"$ne": True},
        }
    ).to_list(length=5000)

    count = 0
    for m in moves:
        qty = m.get("quantity") or 0
        if qty <= 0 or not m.get("product_id"):
            continue
        frm = m.get("from_location_id")
        to = m.get("to_location_id")
        lot = m.get("lot_number")
        serial = m.get("serial_number")
        # Inverso: sacar de `to`, devolver a `from`.
        if to:
            await change_location_stock(
                tenant_id=tenant_id, product_id=m["product_id"],
                warehouse_id=m["warehouse_id"], location_id=to, delta=-qty,
                lot_number=lot, serial_number=serial, allow_negative=True,
            )
        if frm:
            await change_location_stock(
                tenant_id=tenant_id, product_id=m["product_id"],
                warehouse_id=m["warehouse_id"], location_id=frm, delta=qty,
                lot_number=lot, serial_number=serial, allow_negative=True,
            )
        rev = await record_movement(
            tenant_id=tenant_id, movement_type=m.get("movement_type"),
            product_id=m["product_id"], warehouse_id=m["warehouse_id"], quantity=qty,
            from_location_id=to, to_location_id=frm, lot_number=lot, serial_number=serial,
            reference_type=reference_type, reference_id=reference_id, reason=reason,
            created_by=created_by,
        )
        await db[Collections.INVENTORY_MOVEMENTS].update_one(
            {"_id": rev["_id"]}, {"$set": {"is_reversal": True}}
        )
        await db[Collections.INVENTORY_MOVEMENTS].update_one(
            {"_id": m["_id"]}, {"$set": {"reversed": True}}
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Read helpers used by the API layer
# ---------------------------------------------------------------------------
async def list_balances(
    tenant_id: str,
    product_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    location_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    *,
    user: CurrentUser,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {}
    if product_id:
        query["product_id"] = product_id
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    if location_id:
        query["location_id"] = location_id
    if user.warehouse_scoped:
        allowed = set(user.allowed_warehouse_ids)
        if warehouse_id is not None:
            if warehouse_id not in allowed:
                return []
        else:
            query["warehouse_id"] = {"$in": list(allowed)}

    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db[Collections.INVENTORY_BALANCES].count_documents(query)
    balances = (
        await db[Collections.INVENTORY_BALANCES]
        .find(query)
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )

    # Enrich with product / location names for the UI.
    product_ids = {to_object_id(b["product_id"]) for b in balances if b.get("product_id")}
    location_ids = {to_object_id(b["location_id"]) for b in balances if b.get("location_id")}
    products = {
        str(p["_id"]): p
        async for p in db[Collections.PRODUCTS].find({"_id": {"$in": list(product_ids)}})
    }
    locations = {
        str(loc["_id"]): loc
        async for loc in db[Collections.LOCATIONS].find({"_id": {"$in": list(location_ids)}})
    }

    enriched = []
    for b in balances:
        data = serialize(b)
        product = products.get(b.get("product_id"))
        location = locations.get(b.get("location_id"))
        data["sku"] = product.get("sku") if product else None
        data["product_name"] = product.get("name") if product else None
        data["location_code"] = location.get("code") if location else None
        enriched.append(data)
    return page(enriched, total, limit, offset)


async def list_movements(
    tenant_id: str,
    product_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    *,
    user: CurrentUser,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {}
    if product_id:
        query["product_id"] = product_id
    if user.warehouse_scoped:
        query["warehouse_id"] = {"$in": list(user.allowed_warehouse_ids)}
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.INVENTORY_MOVEMENTS].count_documents(query)
    cursor = (
        db[Collections.INVENTORY_MOVEMENTS]
        .find(query)
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    movements = await cursor.to_list(length=limit)
    product_ids = {to_object_id(m["product_id"]) for m in movements if m.get("product_id")}
    products = {
        str(p["_id"]): p
        async for p in db[Collections.PRODUCTS].find({"_id": {"$in": list(product_ids)}})
    }
    result = []
    for m in movements:
        data = serialize(m)
        product = products.get(m.get("product_id"))
        data["sku"] = product.get("sku") if product else None
        result.append(data)
    return page(result, total, limit, offset)
