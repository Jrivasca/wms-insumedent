from typing import Any, Dict, List

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def sync_products(tenant_id: str, actor: str = "system") -> Dict[str, Any]:
    """Artículos que manejan lotes, desde el módulo Inventario (``Inventory/GetBatchesInfo``,
    contratado), por SKU (``code``), más sus lotes como referencia. No es el catálogo
    completo (ese sigue por el importador de Excel).

    - Activos: se crean o actualizan.
    - Inactivos en Defontana: se desactivan si existen en el WMS; no se crean.
    - Defontana no entrega códigos de barra, marca ni familia: los mantiene el importador
      de Excel y el sync no los toca.
    - Lotes (``erp_batches``): foto de referencia que se reemplaza en cada corrida; no
      mueve el stock del WMS.
    """
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    raw_products = await connector.get_products()

    created = updated = deactivated = skipped = 0
    batches: List[Dict[str, Any]] = []
    now = now_utc()

    for raw in raw_products:
        mapped = DefontanaMapper.map_product(raw)
        if not mapped["sku"]:
            skipped += 1
            continue
        batches.extend(DefontanaMapper.map_batches(raw))

        existing = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": tenant_id, "sku": mapped["sku"]}
        )
        if not mapped["is_active"]:
            if existing and existing.get("is_active", True):
                await db[Collections.PRODUCTS].update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"is_active": False, "updated_at": now, "updated_by": actor}},
                )
                deactivated += 1
            else:
                skipped += 1
            continue

        doc = {
            **mapped,
            "tenant_id": tenant_id,
            "updated_at": now,
            "updated_by": actor,
        }
        if existing:
            await db[Collections.PRODUCTS].update_one(
                {"_id": existing["_id"]}, {"$set": doc}
            )
            updated += 1
        else:
            doc["created_at"] = now
            doc["created_by"] = actor
            await db[Collections.PRODUCTS].insert_one(doc)
            created += 1

    await db[Collections.ERP_BATCHES].delete_many({})
    if batches:
        await db[Collections.ERP_BATCHES].insert_many(
            [{**batch, "synced_at": now, "synced_by": actor} for batch in batches]
        )

    return {
        "synced": len(raw_products),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "skipped": skipped,
        "batches": len(batches),
    }
