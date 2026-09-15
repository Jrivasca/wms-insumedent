from datetime import date, timedelta
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.models.notification import NotificationType
from app.models.order import OrderLineStatus, OrderStatus
from app.models.picking import PickingTaskStatus
from app.services import notification_service
from app.services.audit_service import log_action
from app.integrations.defontana.client import DefontanaApiError, DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper

logger = get_logger(__name__)

# Etapas en que el WMS todavía no movió mercadería: el pedido se puede cancelar solo.
UNTOUCHED_STATUSES = (OrderStatus.IMPORTED.value, OrderStatus.PENDING_PICKING.value)
TERMINAL_STATUSES = (OrderStatus.DISPATCHED.value, OrderStatus.CANCELLED.value)
# Tope de pedidos abiertos fuera de la ventana que se reconsultan con Order/Get por corrida.
MAX_STATUS_REFRESH = 200


async def _resolve_product_id(tenant_id: str, sku: Optional[str]) -> Optional[str]:
    if not sku:
        return None
    db = tenant_db(tenant_id)
    product = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": sku})
    return str(product["_id"]) if product else None


async def _reconcile_erp_status(
    tenant_id: str, order: Dict[str, Any], erp_status: str, actor: str
) -> str:
    """Aplica al pedido del WMS el estado actual que tiene en Defontana.

    - Sigue pendiente de guía (``E..``): solo se actualiza ``erp_status``.
    - Ya no se prepara (anulado, cerrado, rechazado, guía emitida fuera del WMS…):
      * sin trabajo físico (importado / picking pendiente) → se cancela solo, con su tarea
        de picking, y queda en auditoría;
      * en preparación → no se toca la operación: se marca ``erp_attention`` y se avisa a
        supervisores una sola vez por cambio de estado;
      * despachado o cancelado en el WMS → solo se actualiza ``erp_status``.

    Devuelve ``cancelled`` / ``flagged`` / ``updated`` / ``unchanged``.
    """
    db = tenant_db(tenant_id)
    now = now_utc()
    order_id = str(order["_id"])
    number = order.get("erp_order_number")
    wms_status = order.get("status")
    changed = erp_status != order.get("erp_status")
    reason = DefontanaMapper.order_no_longer_pending_reason(erp_status)

    if reason is None or wms_status in TERMINAL_STATUSES:
        update: Dict[str, Any] = {}
        if changed:
            update["erp_status"] = erp_status
        if reason is None and order.get("erp_attention"):
            update["erp_attention"] = None  # volvió a estar pendiente de guía
        if not update:
            return "unchanged"
        await db[Collections.ORDERS].update_one(
            {"_id": order["_id"]}, {"$set": {**update, "updated_at": now}}
        )
        return "updated"

    if wms_status in UNTOUCHED_STATUSES:
        await db[Collections.PICKING_TASKS].update_many(
            {"order_id": order_id, "status": {"$ne": PickingTaskStatus.CANCELLED.value}},
            {"$set": {"status": PickingTaskStatus.CANCELLED.value, "updated_at": now,
                      "updated_by": actor}},
        )
        await db[Collections.ORDERS].update_one(
            {"_id": order["_id"]},
            {"$set": {"status": OrderStatus.CANCELLED.value, "erp_status": erp_status,
                      "cancel_reason": reason, "cancelled_at": now, "erp_attention": None,
                      "updated_at": now, "updated_by": actor}},
        )
        await log_action(
            tenant_id=tenant_id, user_id=None, action="erp_order_cancelled",
            entity_type="order", entity_id=order_id,
            before={"status": wms_status, "erp_status": order.get("erp_status")},
            after={"status": OrderStatus.CANCELLED.value, "erp_status": erp_status},
            metadata={"erp_order_number": number, "reason": reason, "source": "defontana"},
        )
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.ERP_ORDER_CHANGED.value,
            title=f"Pedido {number} cancelado",
            body=f"{reason}. Se canceló en el WMS (aún no se había preparado).",
            entity_type="order", entity_id=order_id,
            metadata={"erp_order_number": number, "erp_status": erp_status, "action": "cancelled"},
        )
        return "cancelled"

    # En preparación: avisar sin tocar la operación (una vez por cambio de estado).
    if not changed and order.get("erp_attention"):
        return "unchanged"
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"erp_status": erp_status,
                  "erp_attention": {"reason": reason, "erp_status": erp_status, "detected_at": now},
                  "updated_at": now}},
    )
    await log_action(
        tenant_id=tenant_id, user_id=None, action="erp_order_changed_in_flow",
        entity_type="order", entity_id=order_id,
        before={"erp_status": order.get("erp_status")}, after={"erp_status": erp_status},
        metadata={"erp_order_number": number, "reason": reason, "wms_status": wms_status,
                  "source": "defontana"},
    )
    await notification_service.emit(
        tenant_id=tenant_id,
        notification_type=NotificationType.ERP_ORDER_CHANGED.value,
        title=f"Revisar pedido {number}",
        body=f"{reason}. En el WMS está en «{wms_status}»: revisa si hay que retrocederlo.",
        entity_type="order", entity_id=order_id,
        metadata={"erp_order_number": number, "erp_status": erp_status, "action": "flagged"},
    )
    return "flagged"


async def sync_orders(
    tenant_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    actor: str = "system",
) -> Dict[str, Any]:
    """Importa los pedidos EN DESPACHO de Defontana (los ya despachados se ignoran: el
    WMS no tiene nada que preparar). ``Order/List`` solo trae encabezados, así que el
    detalle de cada pedido pendiente se lee con ``Order/Get``. Sin fechas, la ventana es
    ``DEFONTANA_ORDERS_WINDOW_DAYS`` hacia atrás (90 por defecto).

    Además reconcilia los pedidos ya importados que siguen abiertos en el WMS con su estado
    actual en Defontana (ver :func:`_reconcile_erp_status`); los que quedaron fuera de la
    ventana se reconsultan con ``Order/Get``.
    """
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    today = date.today()
    window = timedelta(days=settings.defontana_orders_window_days)
    from_date = from_date or (today - window).isoformat()
    to_date = to_date or (today + timedelta(days=1)).isoformat()

    headers = await connector.get_orders(from_date, to_date)
    status_by_number = {str(h.get("number")): h.get("status") for h in headers}
    pending = [h for h in headers if DefontanaMapper.is_pending_dispatch(h.get("status"))]

    created = updated = 0
    outcomes: Dict[str, int] = {"cancelled": 0, "flagged": 0}
    handled_numbers = set()
    now = now_utc()

    for header in pending:
        order = await connector.get_order(header.get("number"))
        if not order:
            continue
        mapped = DefontanaMapper.map_order(header, order)
        handled_numbers.add(mapped["erp_order_number"])

        lines = []
        for idx, line in enumerate(mapped["lines"], start=1):
            product_id = await _resolve_product_id(tenant_id, line.get("sku"))
            lines.append(
                {
                    "line_id": f"L{idx}",
                    "product_id": product_id,
                    "sku": line.get("sku"),
                    "name": line.get("name"),
                    "unit": line.get("unit", "UN"),
                    "ordered_quantity": line.get("ordered_quantity", 0),
                    "picked_quantity": 0,
                    "packed_quantity": 0,
                    "status": OrderLineStatus.PENDING.value,
                }
            )

        existing = await db[Collections.ORDERS].find_one(
            {"tenant_id": tenant_id, "erp_order_number": mapped["erp_order_number"]}
        )
        doc = {
            "tenant_id": tenant_id,
            "erp_order_number": mapped["erp_order_number"],
            "erp_document_id": mapped.get("erp_document_id"),
            "erp_status": mapped.get("erp_status"),
            "customer": mapped.get("customer"),
            "order_date": mapped.get("order_date"),
            "delivery_date": mapped.get("delivery_date"),
            "lines": lines,
            "raw_erp_data": mapped.get("raw_erp_data"),
            "updated_at": now,
            "updated_by": actor,
        }
        if existing:
            # Do not clobber an order already in the operational flow.
            if existing.get("status") in UNTOUCHED_STATUSES:
                await db[Collections.ORDERS].update_one(
                    {"_id": existing["_id"]}, {"$set": {**doc, "erp_attention": None}}
                )
                updated += 1
            else:
                await _reconcile_erp_status(tenant_id, existing, mapped.get("erp_status"), actor)
        else:
            doc["status"] = OrderStatus.IMPORTED.value
            doc["is_active"] = True
            doc["created_at"] = now
            doc["created_by"] = actor
            res = await db[Collections.ORDERS].insert_one(doc)
            created += 1
            await notification_service.emit(
                tenant_id=tenant_id,
                notification_type=NotificationType.ORDER_CREATED.value,
                title=f"Nuevo pedido {mapped['erp_order_number']}",
                body=f"{mapped.get('customer') or 'Sin cliente'} · {len(lines)} línea(s) (Defontana)",
                entity_type="order",
                entity_id=str(res.inserted_id),
                metadata={"erp_order_number": mapped["erp_order_number"], "source": "defontana"},
            )

    # Pedidos de Defontana abiertos en el WMS que no se procesaron arriba: traer su estado
    # actual (del listado si está en la ventana, si no con Order/Get) y reconciliar.
    open_orders = await db[Collections.ORDERS].find(
        {"erp_status": {"$exists": True, "$ne": None},
         "status": {"$nin": list(TERMINAL_STATUSES)}}
    ).to_list(length=5000)
    refreshed = 0
    for order in open_orders:
        number = order.get("erp_order_number")
        if number in handled_numbers:
            continue
        erp_status = status_by_number.get(number)
        if erp_status is None:
            if refreshed >= MAX_STATUS_REFRESH:
                continue
            refreshed += 1
            try:
                detail = await connector.get_order(number)
            except DefontanaApiError as exc:
                logger.warning("Defontana Order/Get %s: %s", number, exc)
                continue
            erp_status = (detail or {}).get("status")
        if not erp_status:
            continue
        outcome = await _reconcile_erp_status(tenant_id, order, erp_status, actor)
        if outcome in outcomes:
            outcomes[outcome] += 1

    return {
        "listed": len(headers),
        "synced": len(pending),
        "skipped_not_pending": len(headers) - len(pending),
        "created": created,
        "updated": updated,
        "cancelled": outcomes["cancelled"],
        "flagged": outcomes["flagged"],
    }
