from typing import Any, Dict

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def sync_products(tenant_id: str, actor: str = "system") -> Dict[str, Any]:
    """Upsert del maestro de artículos activos de Defontana por SKU (``code``).

    Defontana no entrega códigos de barra, marca ni familia en este listado: esos datos
    los mantiene el importador de Excel y el sync no los toca.
    """
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    raw_products = await connector.get_products()

    created = updated = skipped = 0
    now = now_utc()

    for raw in raw_products:
        mapped = DefontanaMapper.map_product(raw)
        if not mapped["sku"]:
            skipped += 1
            continue

        existing = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": tenant_id, "sku": mapped["sku"]}
        )
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

    return {
        "synced": len(raw_products),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }
