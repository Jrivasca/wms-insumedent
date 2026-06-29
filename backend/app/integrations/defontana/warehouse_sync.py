from typing import Any, Dict

from app.core.database import get_database
from app.core.utils import now_utc
from app.models import Collections
from app.models.warehouse import WarehouseType
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def sync_warehouses(tenant_id: str, actor: str = "system") -> Dict[str, Any]:
    db = get_database()
    connector = DefontanaConnector(tenant_id)
    raw_storages = await connector.get_warehouses()

    created = updated = 0
    now = now_utc()

    for raw in raw_storages:
        mapped = DefontanaMapper.map_warehouse(raw)
        existing = await db[Collections.WAREHOUSES].find_one(
            {"tenant_id": tenant_id, "erp_storage_code": mapped["erp_storage_code"]}
        )
        doc = {
            **mapped,
            "tenant_id": tenant_id,
            "type": WarehouseType.ERP_STORAGE.value,
            "is_active": True,
            "updated_at": now,
            "updated_by": actor,
        }
        if existing:
            await db[Collections.WAREHOUSES].update_one(
                {"_id": existing["_id"]}, {"$set": doc}
            )
            updated += 1
        else:
            doc["created_at"] = now
            doc["created_by"] = actor
            await db[Collections.WAREHOUSES].insert_one(doc)
            created += 1

    return {"synced": len(raw_storages), "created": created, "updated": updated}
