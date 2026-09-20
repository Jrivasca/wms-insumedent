"""Inventory engine.

Golden rule (section 8.4): stock is never modified without recording a movement.
All public mutators in this module both update ``inventory_balances`` and append a
document to ``inventory_movements``.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.integrations.defontana.mapper import DefontanaMapper
from app.integrations.defontana.schedule import local_now
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.location import COMMITTED_LOCATION_TYPES
from app.models.notification import NotificationType
from app.models.sync_job import SyncJobType
from app.services import notification_service, replenishment_alert_service, sync_job_service

logger = get_logger(__name__)


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
    expiration_date: Optional[datetime] = None,
    notify: bool = True,
) -> Dict[str, Any]:
    """Apply ``delta`` to on-hand stock of a single location and return the balance.

    Does NOT record a movement on its own; callers must pair it with
    :func:`record_movement` (see the higher-level helpers below). ``expiration_date``
    is the lot's expiry (Fase 5); it is only written when provided (on a receipt), so
    operational net-zero moves never wipe it.

    ``notify=False`` calla el aviso de "sin stock" (la conciliación puede dejar en cero cientos
    de productos de una vez); la limpieza de alertas cuando el stock vuelve sigue ocurriendo.
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
    if expiration_date is not None:
        doc["expiration_date"] = expiration_date
    await db[Collections.INVENTORY_BALANCES].update_one(key, {"$set": doc}, upsert=True)

    # Stock-zero alert, edge-triggered and deduped per product+warehouse. Best-effort:
    # a notification failure must never break a stock movement. Only pay the cost when a
    # location actually empties on a decrease (operational net-zero moves keep the
    # warehouse total > 0, so they self-suppress), and re-arm when stock returns.
    if delta < 0 and new_on_hand <= 0:
        if notify:
            await _alert_stock_zero_if_depleted(tenant_id, product_id, warehouse_id)
    elif delta > 0:
        await _clear_stock_zero_if_recovered(tenant_id, product_id, warehouse_id)

    return await db[Collections.INVENTORY_BALANCES].find_one(key)


async def _product_warehouse_total(db, product_id: str, warehouse_id: str) -> float:
    total = 0.0
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"product_id": product_id, "warehouse_id": warehouse_id}
    ):
        total += b.get("quantity_on_hand", 0) or 0
    return total


async def _alert_stock_zero_if_depleted(
    tenant_id: str, product_id: str, warehouse_id: str
) -> None:
    try:
        db = tenant_db(tenant_id)
        if await _product_warehouse_total(db, product_id, warehouse_id) > 0:
            return
        # Edge-trigger: only the first crossing to zero raises an alert.
        already = await db[Collections.STOCK_ALERTS].find_one(
            {"product_id": product_id, "warehouse_id": warehouse_id, "active": True}
        )
        if already:
            return
        now = now_utc()
        await db[Collections.STOCK_ALERTS].update_one(
            {"product_id": product_id, "warehouse_id": warehouse_id},
            {"$set": {"active": True, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        product = await db[Collections.PRODUCTS].find_one({"_id": to_object_id(product_id)})
        warehouse = await db[Collections.WAREHOUSES].find_one({"_id": to_object_id(warehouse_id)})
        sku = (product or {}).get("sku", "")
        name = (product or {}).get("name", sku) or sku
        wh_name = (warehouse or {}).get("name", "")
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.STOCK_ZERO.value,
            title=f"Stock 0: {sku}".strip(),
            body=f"{name} quedó sin stock" + (f" en {wh_name}" if wh_name else ""),
            entity_type="product",
            entity_id=product_id,
            metadata={"product_id": product_id, "warehouse_id": warehouse_id, "sku": sku},
        )
    except Exception as exc:  # noqa: BLE001 - alerting must never break a stock move
        logger.warning("stock-zero alert failed: %s", exc)


async def _clear_stock_zero_if_recovered(
    tenant_id: str, product_id: str, warehouse_id: str
) -> None:
    try:
        db = tenant_db(tenant_id)
        active = await db[Collections.STOCK_ALERTS].find_one(
            {"product_id": product_id, "warehouse_id": warehouse_id, "active": True}
        )
        if not active:
            return
        if await _product_warehouse_total(db, product_id, warehouse_id) > 0:
            await db[Collections.STOCK_ALERTS].update_one(
                {"_id": active["_id"]}, {"$set": {"active": False, "updated_at": now_utc()}}
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stock-zero clear failed: %s", exc)


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
async def _enqueue_inventory_document(
    *,
    tenant_id: str,
    movement: Dict[str, Any],
    product_id: str,
    warehouse_id: str,
    quantity: float,
    document_type: str,
    reason_id: str,
    gloss: str,
    direction: str,
    document_prefix: str,
    created_by: str,
    lot_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    expiration_date: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Encola el documento de inventario hacia Defontana (``Inventory/Insert``).

    Doble llave: el push al ERP en general (``ERP_SYNC_ENABLED``) y el de movimientos de
    inventario en particular (``DEFONTANA_INVENTORY_SYNC_ENABLED``), cuyos valores (tipo de
    documento, motivo, centro de negocio) siguen pendientes de confirmar con Defontana.
    """
    if not (settings.erp_sync_enabled and settings.defontana_inventory_sync_enabled):
        return None
    db = tenant_db(tenant_id)
    product = await db[Collections.PRODUCTS].find_one(
        {"_id": to_object_id(product_id), "tenant_id": tenant_id}
    )
    warehouse = await db[Collections.WAREHOUSES].find_one(
        {"_id": to_object_id(warehouse_id), "tenant_id": tenant_id}
    )
    payload = DefontanaMapper.build_inventory_entry(
        # El prefijo identifica la OPERACIÓN (recepción / ajuste), no el sentido: un ajuste de
        # entrada también es un ajuste.
        external_document_id=f"WMS-{document_prefix}-{movement['_id']}",
        document_type=document_type,
        reason_id=reason_id,
        business_center=settings.defontana_business_center,
        centralizable=settings.defontana_reception_centralizable,
        storage_code=(warehouse or {}).get("erp_storage_code"),
        movement_date=local_now().date(),
        gloss=gloss,
        direction=direction,
        lines=[{
            "code": (product or {}).get("sku"),
            "description": (product or {}).get("name"),
            "count": abs(quantity),
            "price": (product or {}).get("cost") or 0,
            "lot_number": lot_number,
            "expiration_date": expiration_date,
            "serial_number": serial_number,
        }],
    )
    return await sync_job_service.enqueue(
        tenant_id=tenant_id,
        job_type=SyncJobType.CREATE_INVENTORY_DOCUMENT.value,
        payload=payload,
        created_by=created_by,
    )


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
    """Supervisor-approved stock adjustment. ``quantity`` may be negative.

    Cambia la cantidad total de la bodega, así que también viaja a Defontana como documento
    de ajuste (de entrada o de salida según el signo); si no, el ERP y el WMS se descuadran.
    """
    balance = await change_location_stock(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        delta=quantity,
        lot_number=lot_number,
        serial_number=serial_number,
    )
    movement = await record_movement(
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
    incoming = quantity >= 0
    await _enqueue_inventory_document(
        tenant_id=tenant_id,
        movement=movement,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
        document_type=(settings.defontana_adjustment_in_document_type if incoming
                       else settings.defontana_adjustment_out_document_type),
        reason_id=(settings.defontana_adjustment_in_reason_id if incoming
                   else settings.defontana_adjustment_out_reason_id),
        gloss=f"Ajuste WMS: {reason}".strip(),
        direction="in" if incoming else "out",
        document_prefix="AJU",
        created_by=created_by,
        lot_number=lot_number,
        serial_number=serial_number,
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

    # El vencimiento viaja con la mercadería: sin esto el saldo destino nace sin fecha y ese
    # stock deja de ordenarse por FEFO (y desaparece de la vista de vencimientos).
    source = await tenant_db(tenant_id)[Collections.INVENTORY_BALANCES].find_one({
        "tenant_id": tenant_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "location_id": from_location_id,
        "lot_number": lot_number,
        "serial_number": serial_number,
    })
    expiration_date = (source or {}).get("expiration_date")

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
        expiration_date=expiration_date,
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


async def putaway(
    *,
    tenant_id: str,
    balance_id: str,
    to_location_id: str,
    quantity: float,
    user: CurrentUser,
) -> Dict[str, Any]:
    """Mueve un saldo EXACTO a otra ubicación de la misma bodega ("Ubicar stock").

    A diferencia de :func:`create_transfer`, que recibe producto + lote y tiene que adivinar
    de qué saldo sale, acá el saldo llega identificado: lote, serie y vencimiento son los de
    esa fila, así que no hay forma de mover el stock equivocado ni de perder la fecha.

    Es un movimiento interno de la bodega: el ERP no se entera (Defontana manda las
    cantidades, el WMS manda las ubicaciones), por lo que NO crea ningún job de sincronización.
    """
    db = tenant_db(tenant_id)
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor que cero")

    balance = await db[Collections.INVENTORY_BALANCES].find_one(
        {"_id": to_object_id(balance_id), "tenant_id": tenant_id}
    )
    if not balance:
        raise HTTPException(status_code=404, detail="El saldo no existe")

    warehouse_id = balance.get("warehouse_id")
    user.assert_warehouse_allowed(warehouse_id)

    from_location_id = balance.get("location_id")
    if from_location_id == to_location_id:
        raise HTTPException(status_code=400, detail="El origen y el destino son la misma ubicación")

    origin = await db[Collections.LOCATIONS].find_one({"_id": to_object_id(from_location_id)})
    if origin and origin.get("type") in COMMITTED_LOCATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Esa mercadería está en preparación ({origin.get('code')}): "
                    "sale por el pedido o reabriendo su tarea, no reubicándola."),
        )

    destination = await db[Collections.LOCATIONS].find_one({"_id": to_object_id(to_location_id)})
    if not destination:
        raise HTTPException(status_code=404, detail="La ubicación de destino no existe")
    if destination.get("warehouse_id") != warehouse_id:
        raise HTTPException(
            status_code=400, detail="La ubicación de destino es de otra bodega")
    if destination.get("is_active") is False:
        raise HTTPException(
            status_code=400,
            detail=f"La ubicación {destination.get('code')} está inactiva")
    if destination.get("type") in COMMITTED_LOCATION_TYPES:
        # Esas ubicaciones son de pedidos en preparación: dejar ahí stock suelto lo haría
        # invisible para el picking (no es pickeable) sin que ningún pedido lo reclame.
        raise HTTPException(
            status_code=400,
            detail=(f"{destination.get('code')} es una ubicación de trabajo: "
                    "ahí solo llega mercadería por un pedido."),
        )

    available = _available(balance)
    if quantity > available + 1e-9:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Solo hay {available:g} disponible(s) en ese saldo")

    common = {
        "tenant_id": tenant_id,
        "product_id": balance.get("product_id"),
        "warehouse_id": warehouse_id,
        "lot_number": balance.get("lot_number"),
        "serial_number": balance.get("serial_number"),
    }
    await change_location_stock(**common, location_id=from_location_id, delta=-quantity)
    destination_balance = await change_location_stock(
        **common,
        location_id=to_location_id,
        delta=quantity,
        expiration_date=balance.get("expiration_date"),
    )
    movement = await record_movement(
        tenant_id=tenant_id,
        movement_type=MovementType.TRANSFER.value,
        product_id=balance.get("product_id"),
        warehouse_id=warehouse_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity=quantity,
        lot_number=balance.get("lot_number"),
        serial_number=balance.get("serial_number"),
        reference_type=ReferenceType.MANUAL.value,
        created_by=user.id,
    )
    return {
        "movement": serialize(movement),
        "balance": serialize(destination_balance),
        "from_location_code": (origin or {}).get("code"),
        "to_location_code": destination.get("code"),
    }


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
    expiration_date: Optional[datetime] = None,
    sync_erp: bool = True,
) -> Dict[str, Any]:
    """Receive inbound stock into a location (entrada de mercadería).

    Adds stock + records a RECEIPT movement, and (optionally) enqueues an ERP
    inventory-entry document (Defontana ``POST /Inventory/Insert``, real-supported).
    ``expiration_date`` (Fase 5) is stored on the lot's balance for FEFO + alerts.
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
        expiration_date=expiration_date,
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

    # Avisar a bodega si este ingreso destraba pedidos que quedaron parciales.
    await replenishment_alert_service.notify_after_receipt(
        tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        actor_id=created_by,
    )

    job = None
    if sync_erp:
        job = await _enqueue_inventory_document(
            tenant_id=tenant_id,
            movement=movement,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            document_type=settings.defontana_reception_document_type,
            reason_id=settings.defontana_reception_reason_id,
            gloss=f"Recepción WMS {reference}".strip() if reference else "Recepción WMS",
            direction="in",
            document_prefix="REC",
            created_by=created_by,
            lot_number=lot_number,
            serial_number=serial_number,
            expiration_date=expiration_date,
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
# Lotes y vencimiento (Fase 5): alerta "por vencer"
# ---------------------------------------------------------------------------
def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def check_expiring_stock(tenant_id: str, days: Optional[int] = None) -> int:
    """Alert on lots that expire within ``days`` (default ``expiry_alert_days``) and
    still have stock. Deduped per (product, warehouse, lot) via ``expiry_alerts``, so a
    lot only alerts once when it enters the window. Returns how many it alerted."""
    days = settings.expiry_alert_days if days is None else days
    db = tenant_db(tenant_id)
    now = now_utc()
    threshold = now + timedelta(days=days)
    alerted = 0
    cursor = db[Collections.INVENTORY_BALANCES].find(
        {"expiration_date": {"$ne": None, "$lte": threshold}, "quantity_on_hand": {"$gt": 0}}
    )
    async for bal in cursor:
        pid = bal.get("product_id")
        wid = bal.get("warehouse_id")
        lot = bal.get("lot_number")
        marker = {"product_id": pid, "warehouse_id": wid, "lot_number": lot}
        if await db[Collections.EXPIRY_ALERTS].find_one({**marker, "active": True}):
            continue
        await db[Collections.EXPIRY_ALERTS].update_one(
            marker,
            {"$set": {**marker, "active": True, "updated_at": now,
                      "expiration_date": bal.get("expiration_date")}},
            upsert=True,
        )
        product = await db[Collections.PRODUCTS].find_one({"_id": to_object_id(pid)})
        sku = (product or {}).get("sku", "") or ""
        name = (product or {}).get("name", sku) or sku
        exp = _aware(bal.get("expiration_date"))
        exp_str = exp.date().isoformat() if exp else "?"
        expired = bool(exp and exp <= now)
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.STOCK_EXPIRING.value,
            title=(f"Vencido: {sku}" if expired else f"Por vencer: {sku}").strip(),
            body=f"{name} · lote {lot or 's/l'} vence {exp_str} · {bal.get('quantity_on_hand')} u",
            entity_type="product",
            entity_id=pid,
            metadata={"product_id": pid, "warehouse_id": wid, "lot_number": lot,
                      "expiration_date": exp_str},
        )
        alerted += 1
    return alerted


# ---------------------------------------------------------------------------
# Read helpers used by the API layer
# ---------------------------------------------------------------------------
EXPIRY_BUCKETS = ("expired", "d30", "d90", "d180")


def _expiry_bucket(expiration: datetime, now: datetime) -> str:
    """En qué tramo cae un vencimiento: vencido, ≤30 d, 31–90 d, 91–180 d (o más)."""
    dias = (_aware(expiration) - now).days
    if dias < 0:
        return "expired"
    if dias <= 30:
        return "d30"
    if dias <= 90:
        return "d90"
    return "d180"


async def expiring_stock(
    tenant_id: str,
    *,
    user: CurrentUser,
    days: int = 180,
    q: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    location_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Stock vencido y por vencer dentro de ``days``, en orden FEFO.

    Solo saldos con stock y con fecha: sin unidades no hay nada que hacer, y sin fecha no se
    puede clasificar. El resumen cuenta TODO lo filtrado, no solo la página que se muestra.

    Es independiente de las notificaciones: el worker avisa a 30 días
    (``expiry_alert_days``) y una sola vez por lote; esta vista mira más lejos y se puede
    consultar cuando se quiera.
    """
    db = tenant_db(tenant_id)
    now = now_utc()
    days = max(0, min(days, 3650))
    query: Dict[str, Any] = {
        "quantity_on_hand": {"$gt": 0},
        "expiration_date": {"$ne": None, "$lte": now + timedelta(days=days)},
    }
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    if location_id:
        query["location_id"] = location_id
    if user.warehouse_scoped:
        allowed = set(user.allowed_warehouse_ids)
        if warehouse_id is not None:
            if warehouse_id not in allowed:
                return {**page([], 0, limit, offset), "summary": _empty_expiry_summary(days)}
        else:
            query["warehouse_id"] = {"$in": list(allowed)}
    await _apply_text_search(db, query, q)

    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db[Collections.INVENTORY_BALANCES].count_documents(query)
    rows = (
        await db[Collections.INVENTORY_BALANCES]
        .find(query)
        # FEFO: primero lo que vence antes. El ``_id`` desempata para que paginar sea estable.
        .sort([("expiration_date", 1), ("_id", 1)])
        .skip(offset)
        .limit(limit)
        .to_list(length=limit)
    )

    products = {
        str(p["_id"]): p
        async for p in db[Collections.PRODUCTS].find(
            {"_id": {"$in": [to_object_id(r["product_id"]) for r in rows if r.get("product_id")]}}
        )
    }
    locations = {
        str(loc["_id"]): loc
        async for loc in db[Collections.LOCATIONS].find(
            {"_id": {"$in": [to_object_id(r["location_id"]) for r in rows if r.get("location_id")]}}
        )
    }

    items = []
    for row in rows:
        data = serialize(row)
        product = products.get(row.get("product_id"))
        location = locations.get(row.get("location_id"))
        expiration = _aware(row.get("expiration_date"))
        data["sku"] = (product or {}).get("sku")
        data["product_name"] = (product or {}).get("name")
        data["location_code"] = (location or {}).get("code")
        data["location_type"] = (location or {}).get("type")
        data["days_left"] = (expiration - now).days if expiration else None
        data["bucket"] = _expiry_bucket(row["expiration_date"], now)
        items.append(data)

    # Resumen sobre todo lo filtrado, no solo sobre la página. Se clasifica en Python con la
    # misma ``_expiry_bucket`` que las filas, para que resumen y detalle no puedan discrepar;
    # hacerlo en la base exigiría repetir los cortes en un ``$switch`` que además compara
    # fechas con y sin zona horaria según de dónde vengan. Solo recorre lo que ya está
    # acotado por el horizonte, con dos campos por documento.
    summary = _empty_expiry_summary(days)
    async for row in db[Collections.INVENTORY_BALANCES].find(
        query, {"expiration_date": 1, "quantity_on_hand": 1}
    ):
        bucket = summary["buckets"][_expiry_bucket(row["expiration_date"], now)]
        bucket["rows"] += 1
        bucket["units"] += row.get("quantity_on_hand") or 0
    summary["rows"] = total
    summary["units"] = sum(b["units"] for b in summary["buckets"].values())
    return {**page(items, total, limit, offset), "summary": summary}


def _empty_expiry_summary(days: int) -> Dict[str, Any]:
    return {
        "days": days,
        "rows": 0,
        "units": 0,
        "buckets": {b: {"rows": 0, "units": 0} for b in EXPIRY_BUCKETS},
    }


async def _product_ids_matching(db, needle: str, cap: int = 2000) -> List[str]:
    """Ids de productos cuyo SKU, nombre o código de barras contiene ``needle``.

    Los saldos guardan solo ``product_id``, así que una búsqueda por texto se resuelve en dos
    pasos. ``cap`` acota la lista para no armar un ``$in`` gigante con una búsqueda muy corta.
    """
    rx = {"$regex": re.escape(needle), "$options": "i"}
    ids = {
        str(p["_id"])
        async for p in db[Collections.PRODUCTS].find(
            {"$or": [{"sku": rx}, {"name": rx}]}, {"_id": 1}
        ).limit(cap)
    }
    async for bc in db[Collections.BARCODES].find({"barcode": rx}, {"product_id": 1}).limit(cap):
        ids.add(bc.get("product_id"))
    return [i for i in ids if i]


async def _apply_text_search(db, query: Dict[str, Any], q: Optional[str]) -> None:
    """Agrega a ``query`` la búsqueda por texto: lote y serie viven en el saldo; SKU, nombre y
    código de barras se resuelven primero a ``product_id``. Compartido por la consulta de
    saldos y la de vencimientos, para que busquen igual."""
    if not q or not q.strip():
        return
    needle = q.strip()
    rx = {"$regex": re.escape(needle), "$options": "i"}
    query["$or"] = [{"lot_number": rx}, {"serial_number": rx}]
    matches = await _product_ids_matching(db, needle)
    if matches:
        query["$or"].append({"product_id": {"$in": matches}})


async def list_balances(
    tenant_id: str,
    product_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    location_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    *,
    user: CurrentUser,
    q: Optional[str] = None,
    positive_only: bool = True,
) -> Dict[str, Any]:
    """Saldos paginados. ``q`` busca en SKU, nombre, código de barras, lote y serie; la
    búsqueda es del lado del servidor, sobre TODOS los saldos y no solo la página cargada.
    ``positive_only`` (por defecto) esconde las filas en cero, que son historia, no stock."""
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {}
    if product_id:
        query["product_id"] = product_id
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    if location_id:
        query["location_id"] = location_id
    if positive_only:
        query["quantity_on_hand"] = {"$gt": 0}
    if user.warehouse_scoped:
        allowed = set(user.allowed_warehouse_ids)
        if warehouse_id is not None:
            if warehouse_id not in allowed:
                return page([], 0, limit, offset)
        else:
            query["warehouse_id"] = {"$in": list(allowed)}
    await _apply_text_search(db, query, q)

    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    total = await db[Collections.INVENTORY_BALANCES].count_documents(query)
    balances = (
        await db[Collections.INVENTORY_BALANCES]
        .find(query)
        # Orden fijo: sin él, saltar de página puede repetir u ocultar filas.
        .sort([("product_id", 1), ("location_id", 1), ("_id", 1)])
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
