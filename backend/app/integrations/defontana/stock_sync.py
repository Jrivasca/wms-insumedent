"""Foto del stock de Defontana (``Inventory/GetFutureStockInfo``).

Solo lectura: se guarda en ``erp_stock`` para compararla con el stock del WMS (ver
``erp_stock_service``). No modifica ningún saldo del WMS; quién manda sobre el stock
está pendiente de definir.
"""
from typing import Any, Dict

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper


async def sync_erp_stock(tenant_id: str, actor: str = "system") -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    connector = DefontanaConnector(tenant_id)
    raw = await connector.get_stock_levels()
    now = now_utc()

    rows = [
        {**row, "synced_at": now, "synced_by": actor}
        for item in raw
        for row in DefontanaMapper.map_stock(item)
        if row.get("sku") and row.get("storage_code")
    ]
    # La foto anterior se reemplaza completa: refleja el estado del ERP en este momento.
    await db[Collections.ERP_STOCK].delete_many({})
    if rows:
        await db[Collections.ERP_STOCK].insert_many(rows)
    await db[Collections.ERP_CONNECTIONS].update_one(
        {"erp": "defontana"}, {"$set": {"last_stock_sync_at": now}}
    )
    return {"products": len(raw), "rows": len(rows)}
