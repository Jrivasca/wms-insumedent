"""Stock disponible para picking, descontando lo que ya tomaron los pickings abiertos.

El escaneo de picking no mueve stock: la mercadería pasa de su ubicación a staging recién
al cerrar la tarea (``picking_service.complete``), y ese movimiento no bloquea
(``allow_negative``). Sin esto, nada impedía escanear más de lo que hay en el estante, ni que
dos pedidos en paralelo escanearan las mismas unidades: el segundo cierre dejaba el saldo
negativo en silencio.

Lo escaneado en una tarea abierta (pendiente o en curso) cuenta como **tomado** desde el
momento del escaneo: se resta del disponible de esa ubicación (y lote) para cualquier otro
escaneo, de esta tarea o de otra. Es una reserva derivada de los escaneos, no un campo
aparte: no hay ``quantity_reserved`` que mantener ni que se desincronice, y al cerrar,
cancelar o reiniciar la línea la reserva desaparece sola con los escaneos.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import to_object_id
from app.models import Collections
from app.models.location import NON_PICKABLE_LOCATION_TYPES, LocationType
from app.models.notification import NotificationType
from app.models.picking import PickingTaskStatus
from app.services import notification_service

logger = get_logger(__name__)

OPEN_PICKING_STATUSES = (PickingTaskStatus.PENDING.value, PickingTaskStatus.IN_PROGRESS.value)

Key = Tuple[Optional[str], Optional[str]]  # (ubicación, lote)


async def taken_by_open_picking(db, product_id: str, warehouse_id: str) -> Dict[Key, float]:
    """Unidades escaneadas en pickings abiertos, por (ubicación, lote)."""
    taken: Dict[Key, float] = {}
    async for task in db[Collections.PICKING_TASKS].find(
        {
            "warehouse_id": warehouse_id,
            "status": {"$in": list(OPEN_PICKING_STATUSES)},
            "lines.product_id": product_id,
        },
        {"lines": 1},
    ):
        for line in task.get("lines", []):
            if line.get("product_id") != product_id:
                continue
            for s in line.get("scans", []):
                qty = s.get("quantity", 0) or 0
                if qty <= 0:
                    continue
                key = (s.get("location_id") or line.get("suggested_location_id"), s.get("lot_number") or None)
                taken[key] = taken.get(key, 0) + qty
    return taken


async def demand_of_open_picking(
    db, product_id: str, warehouse_id: str, exclude_task_id: Optional[str] = None
) -> float:
    """Lo que piden (no solo lo escaneado) las otras tareas de picking abiertas."""
    total = 0.0
    async for task in db[Collections.PICKING_TASKS].find(
        {
            "warehouse_id": warehouse_id,
            "status": {"$in": list(OPEN_PICKING_STATUSES)},
            "lines.product_id": product_id,
        },
        {"lines": 1},
    ):
        if exclude_task_id and str(task["_id"]) == exclude_task_id:
            continue
        for line in task.get("lines", []):
            if line.get("product_id") == product_id:
                total += line.get("quantity_required", 0) or 0
    return total


async def _non_pickable_ids(db, warehouse_id: str) -> set:
    return {
        str(loc["_id"])
        async for loc in db[Collections.LOCATIONS].find(
            {"warehouse_id": warehouse_id, "type": {"$in": list(NON_PICKABLE_LOCATION_TYPES)}},
            {"_id": 1},
        )
    }


def _usable(balance: Dict[str, Any]) -> float:
    return (
        (balance.get("quantity_on_hand", 0) or 0)
        - (balance.get("quantity_reserved", 0) or 0)
        - (balance.get("quantity_blocked", 0) or 0)
    )


async def available_by_location(db, product_id: str, warehouse_id: str) -> List[Dict[str, Any]]:
    """Disponible para pickear por (ubicación, lote), ya descontado lo tomado.

    Solo ubicaciones pickeables: staging, packing, despacho, cuarentena y recepción no
    cuentan (ver ``NON_PICKABLE_LOCATION_TYPES``).
    """
    excluded = await _non_pickable_ids(db, warehouse_id)
    taken = await taken_by_open_picking(db, product_id, warehouse_id)
    rows: Dict[Key, Dict[str, Any]] = {}
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"product_id": product_id, "warehouse_id": warehouse_id}
    ):
        loc = b.get("location_id")
        if not loc or loc in excluded:
            continue
        key = (loc, b.get("lot_number") or None)
        row = rows.setdefault(key, {"location_id": loc, "lot_number": key[1], "on_hand": 0.0})
        row["on_hand"] += _usable(b)
    out = []
    for key, row in rows.items():
        row["taken"] = taken.get(key, 0.0)
        row["available"] = max(0.0, row["on_hand"] - row["taken"])
        out.append(row)
    return out


async def location_codes(db, location_ids: List[str]) -> Dict[str, str]:
    ids = [to_object_id(i) for i in location_ids if i]
    return {
        str(loc["_id"]): loc.get("code") or str(loc["_id"])
        async for loc in db[Collections.LOCATIONS].find({"_id": {"$in": ids}}, {"code": 1})
    }


async def unplaced_quantity(db, product_id: str, warehouse_id: str) -> float:
    """Lo que está en recepción, todavía sin ubicar: existe, pero no se puede pickear."""
    ids = [
        str(loc["_id"])
        async for loc in db[Collections.LOCATIONS].find(
            {"warehouse_id": warehouse_id, "type": LocationType.RECEIVING.value}, {"_id": 1}
        )
    ]
    total = 0.0
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"product_id": product_id, "warehouse_id": warehouse_id, "location_id": {"$in": ids}}
    ):
        total += b.get("quantity_on_hand", 0) or 0
    return total


async def is_pickable_location(db, warehouse_id: str, location_id: str) -> bool:
    return location_id not in await _non_pickable_ids(db, warehouse_id)


# ---------------------------------------------------------------------------
# Alertas de quiebre de stock
# ---------------------------------------------------------------------------

def _fmt(q: float) -> str:
    return f"{q:g}"


async def alert_shortage_on_new_task(tenant_id: str, task: Dict[str, Any]) -> None:
    """Al generar el picking: avisa si el pedido pide más de lo que queda libre.

    Libre = lo pickeable en la bodega menos lo que piden las otras tareas abiertas (aunque
    todavía no lo escaneen): dos pedidos por las mismas 5 unidades avisan en el segundo, no
    recién cuando alguien se queda corto en el estante. Best-effort: nunca rompe el picking.
    """
    try:
        db = tenant_db(tenant_id)
        task_id = str(task.get("_id") or task.get("id"))
        cortas = []
        for line in task.get("lines", []):
            pid = line.get("product_id")
            req = line.get("quantity_required", 0) or 0
            if not pid or req <= 0:
                continue
            rows = await available_by_location(db, pid, task["warehouse_id"])
            on_hand = sum(r["on_hand"] for r in rows)
            libre = on_hand - await demand_of_open_picking(db, pid, task["warehouse_id"], task_id)
            if libre < req:
                cortas.append(f"{line.get('sku')} (pide {_fmt(req)}, libre {_fmt(max(libre, 0))})")
        if not cortas:
            return
        numero = task.get("erp_order_number") or task.get("order_id")
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.STOCK_SHORTAGE.value,
            title=f"Quiebre de stock: pedido {numero}",
            body="No alcanza el stock para: " + "; ".join(cortas) + ".",
            entity_type="order",
            entity_id=task.get("order_id"),
            metadata={"order_id": task.get("order_id"), "stage": "picking_created", "lines": cortas},
        )
    except Exception as exc:  # noqa: BLE001 - una alerta nunca bloquea el picking
        logger.warning("alerta de quiebre (nuevo picking) falló: %s", exc)


async def alert_shortage_on_close(tenant_id: str, task: Dict[str, Any]) -> None:
    """Al cerrar el picking incompleto: avisa qué faltó. Best-effort."""
    try:
        faltan = []
        for line in task.get("lines", []):
            req = line.get("quantity_required", 0) or 0
            got = line.get("quantity_picked", 0) or 0
            if got < req:
                faltan.append(f"{line.get('sku')} (faltan {_fmt(req - got)} de {_fmt(req)})")
        if not faltan:
            return
        numero = task.get("erp_order_number") or task.get("order_id")
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.STOCK_SHORTAGE.value,
            title=f"Pedido {numero} quedó incompleto",
            body="Se cerró el picking sin: " + "; ".join(faltan) + ".",
            entity_type="order",
            entity_id=task.get("order_id"),
            metadata={"order_id": task.get("order_id"), "stage": "picking_closed", "lines": faltan},
            # Sin excluir a quien cerró: el quiebre es un pendiente a seguir, no un aviso de
            # "otro hizo algo", y quien cierra puede ser el único supervisor.
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("alerta de quiebre (cierre incompleto) falló: %s", exc)
