from datetime import date, timedelta
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.models.notification import NotificationType
from app.models.order import OrderLineStatus, OrderStatus
from app.services import notification_service
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def _resolve_product_id(tenant_id: str, sku: Optional[str]) -> Optional[str]:
    if not sku:
        return None
    db = tenant_db(tenant_id)
    product = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": sku})
    return str(product["_id"]) if product else None


async def sync_orders(
    tenant_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    actor: str = "system",
) -> Dict[str, Any]:
    """Importa los pedidos EN DESPACHO de Defontana (los ya despachados se ignoran: el
    WMS no tiene nada que preparar). ``Order/List`` solo trae encabezados, así que el
    detalle de cada pedido pendiente se lee con ``Order/Get``. Sin fechas, la ventana es
    ``DEFONTANA_ORDERS_WINDOW_DAYS`` hacia atrás (90 por defecto)."""
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    today = date.today()
    window = timedelta(days=settings.defontana_orders_window_days)
    from_date = from_date or (today - window).isoformat()
    to_date = to_date or (today + timedelta(days=1)).isoformat()

    headers = await connector.get_orders(from_date, to_date)
    pending = [h for h in headers if DefontanaMapper.is_pending_dispatch(h.get("status"))]

    created = updated = 0
    now = now_utc()

    for header in pending:
        order = await connector.get_order(header.get("number"))
        if not order:
            continue
        mapped = DefontanaMapper.map_order(header, order)

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
            if existing.get("status") in (
                OrderStatus.IMPORTED.value,
                OrderStatus.PENDING_PICKING.value,
            ):
                await db[Collections.ORDERS].update_one(
                    {"_id": existing["_id"]}, {"$set": doc}
                )
                updated += 1
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

    return {
        "listed": len(headers),
        "synced": len(pending),
        "skipped_not_pending": len(headers) - len(pending),
        "created": created,
        "updated": updated,
    }
