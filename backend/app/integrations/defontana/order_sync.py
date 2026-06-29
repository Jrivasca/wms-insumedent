from typing import Any, Dict, Optional

from app.core.database import get_database
from app.core.utils import now_utc
from app.models import Collections
from app.models.order import OrderLineStatus, OrderStatus
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def _resolve_product_id(tenant_id: str, sku: Optional[str]) -> Optional[str]:
    if not sku:
        return None
    db = get_database()
    product = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": sku})
    return str(product["_id"]) if product else None


async def sync_orders(
    tenant_id: str,
    from_date: str = "2020-01-01",
    to_date: str = "2999-12-31",
    actor: str = "system",
) -> Dict[str, Any]:
    db = get_database()
    connector = DefontanaConnector(tenant_id)
    raw_orders = await connector.get_orders(from_date, to_date)

    created = updated = 0
    now = now_utc()

    for raw in raw_orders:
        mapped = DefontanaMapper.map_order(raw)

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
            await db[Collections.ORDERS].insert_one(doc)
            created += 1

    return {"synced": len(raw_orders), "created": created, "updated": updated}
