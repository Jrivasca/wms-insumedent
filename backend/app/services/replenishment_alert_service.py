"""Alerta de reposición: entró stock que permite completar pedidos parciales.

Requerimiento 1 de docs/levantamiento-alertas-recepcion-y-match.md. Cuando se recibe
mercadería, avisa a bodega qué pedidos que quedaron PARCIALES por falta de ese producto
ya se pueden completar, para que el operario los retome solo ("Completar faltante",
``picking_service.resume_partial``) sin esperar a que el jefe le avise.

Reglas:
- Solo pedidos ``fulfillment=partial`` en una etapa desde la que se puede reabrir el
  picking (picked → ready_to_dispatch). Uno despachado en parte exige anular la guía
  (supervisor), así que no se ofrece.
- Solo cuenta stock pickeable: se excluyen las ubicaciones operativas (staging, packing,
  dispatch) y cuarentena, donde la mercadería ya está comprometida o bloqueada.
- Una línea es completable si el disponible cubre TODO su faltante. El stock se asigna
  al pedido más antiguo primero, para no avisar dos pedidos con las mismas unidades.
- Sin duplicados: un marcador activo por (pedido, producto) en ``replenishment_alerts``;
  se libera al retomar el pedido (reapertura de picking).
- Best-effort: un fallo del aviso nunca rompe la recepción.
"""
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.models.location import LocationType
from app.models.notification import NotificationType
from app.models.order import OrderFulfillment, OrderStatus
from app.models.picking import PickingTaskStatus
from app.services import notification_service

logger = get_logger(__name__)

# Etapas desde las que se puede reabrir el picking (ver picking_service.reopen_picking).
RESUMABLE_STATUSES = (
    OrderStatus.PICKED.value,
    OrderStatus.PACKING.value,
    OrderStatus.PACKED.value,
    OrderStatus.READY_TO_DISPATCH.value,
)

# Ubicaciones cuyo stock no está disponible para pickear.
NON_PICKABLE_LOCATION_TYPES = (
    LocationType.STAGING.value,
    LocationType.PACKING.value,
    LocationType.DISPATCH.value,
    LocationType.QUARANTINE.value,
)


def _shortfall(line: Dict[str, Any]) -> float:
    return max(0, (line.get("ordered_quantity", 0) or 0) - (line.get("picked_quantity", 0) or 0))


async def pickable_available(db, product_id: str, warehouse_id: str) -> float:
    """Disponible (on_hand - reservado - bloqueado) del producto en la bodega, fuera de
    las ubicaciones operativas/cuarentena."""
    excluded = {
        str(loc["_id"])
        async for loc in db[Collections.LOCATIONS].find(
            {"warehouse_id": warehouse_id, "type": {"$in": list(NON_PICKABLE_LOCATION_TYPES)}}
        )
    }
    total = 0.0
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"product_id": product_id, "warehouse_id": warehouse_id}
    ):
        if b.get("location_id") in excluded:
            continue
        total += (
            (b.get("quantity_on_hand", 0) or 0)
            - (b.get("quantity_reserved", 0) or 0)
            - (b.get("quantity_blocked", 0) or 0)
        )
    return max(0.0, total)


async def _order_warehouse_id(db, order: Dict[str, Any]) -> Optional[str]:
    task = await db[Collections.PICKING_TASKS].find_one(
        {"order_id": str(order["_id"]), "status": {"$ne": PickingTaskStatus.CANCELLED.value}}
    )
    return (task or {}).get("warehouse_id") or order.get("warehouse_id")


async def evaluate_completable(
    tenant_id: str,
    *,
    product_id: Optional[str] = None,
    order_id: Optional[str] = None,
    warehouse_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Pedidos parciales retomables con al menos una línea cuyo faltante completo ya
    está cubierto por stock pickeable. El stock se asigna del pedido más antiguo al más
    nuevo. Filtros opcionales: pedidos que contienen ``product_id``, un ``order_id``
    puntual, o bodegas permitidas (``warehouse_ids``)."""
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {
        "fulfillment": OrderFulfillment.PARTIAL.value,
        "status": {"$in": list(RESUMABLE_STATUSES)},
    }
    if product_id:
        query["lines.product_id"] = product_id
    if order_id:
        query["_id"] = to_object_id(order_id)
    allowed = set(warehouse_ids) if warehouse_ids is not None else None

    orders = await db[Collections.ORDERS].find(query).sort("created_at", 1).to_list(length=1000)
    remaining: Dict[Tuple[str, str], float] = {}
    result: List[Dict[str, Any]] = []
    for order in orders:
        warehouse_id = await _order_warehouse_id(db, order)
        if not warehouse_id or (allowed is not None and warehouse_id not in allowed):
            continue
        lines = []
        for line in order.get("lines", []):
            pid = line.get("product_id")
            missing = _shortfall(line)
            if not pid or missing <= 0:
                continue
            key = (pid, warehouse_id)
            if key not in remaining:
                remaining[key] = await pickable_available(db, pid, warehouse_id)
            if remaining[key] < missing:
                continue
            lines.append(
                {
                    "line_id": line.get("line_id"),
                    "product_id": pid,
                    "sku": line.get("sku"),
                    "name": line.get("name"),
                    "missing": missing,
                    "available": remaining[key],
                }
            )
            remaining[key] -= missing
        if lines:
            result.append(
                {
                    "order_id": str(order["_id"]),
                    "erp_order_number": order.get("erp_order_number"),
                    "customer": order.get("customer"),
                    "status": order.get("status"),
                    "warehouse_id": warehouse_id,
                    "lines": lines,
                }
            )
    return result


async def notify_after_receipt(
    *, tenant_id: str, product_id: str, warehouse_id: str, actor_id: Optional[str] = None
) -> int:
    """Tras recibir ``product_id`` en ``warehouse_id``: avisa (una notificación) los
    pedidos parciales que ahora se pueden completar y que no tenían ya un aviso activo
    por ese producto. Devuelve cuántos pedidos avisó. Nunca lanza."""
    try:
        db = tenant_db(tenant_id)
        ready: List[Dict[str, Any]] = []
        for entry in await evaluate_completable(
            tenant_id, product_id=product_id, warehouse_ids=[warehouse_id]
        ):
            if not any(l["product_id"] == product_id for l in entry["lines"]):
                continue  # el stock de este producto se lo llevó un pedido más antiguo
            marker = {"order_id": entry["order_id"], "product_id": product_id}
            if await db[Collections.REPLENISHMENT_ALERTS].find_one({**marker, "active": True}):
                continue
            now = now_utc()
            await db[Collections.REPLENISHMENT_ALERTS].update_one(
                marker,
                {"$set": {**marker, "active": True, "warehouse_id": warehouse_id,
                          "updated_at": now},
                 "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            ready.append(entry)
        if not ready:
            return 0

        product = await db[Collections.PRODUCTS].find_one({"_id": to_object_id(product_id)})
        sku = (product or {}).get("sku", "") or ""
        name = (product or {}).get("name", sku) or sku
        numbers = [f"#{e['erp_order_number']}" for e in ready]
        target = "el pedido" if len(ready) == 1 else "los pedidos"
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.RECEIPT_UNBLOCKS_ORDER.value,
            title=f"Llegó stock: {sku}".strip(),
            body=f"{name} · ya puedes completar {target} {', '.join(numbers)}",
            entity_type="order",
            entity_id=ready[0]["order_id"],
            metadata={
                "product_id": product_id,
                "sku": sku,
                "warehouse_id": warehouse_id,
                "order_ids": [e["order_id"] for e in ready],
                "erp_order_numbers": [e["erp_order_number"] for e in ready],
            },
            actor_id=actor_id,
        )
        return len(ready)
    except Exception as exc:  # noqa: BLE001 - alerting must never break a reception
        logger.warning("replenishment alert failed: %s", exc)
        return 0


async def release_for_order(tenant_id: str, order_id: str) -> None:
    """Libera los marcadores del pedido (se retomó): un próximo faltante vuelve a avisar."""
    try:
        db = tenant_db(tenant_id)
        await db[Collections.REPLENISHMENT_ALERTS].update_many(
            {"order_id": order_id, "active": True},
            {"$set": {"active": False, "updated_at": now_utc()}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("replenishment alert release failed: %s", exc)
