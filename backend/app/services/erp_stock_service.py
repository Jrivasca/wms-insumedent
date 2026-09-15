"""Comparación del stock de Defontana con el stock del WMS.

Cruza la última foto de ``erp_stock`` (``Inventory/GetFutureStockInfo``) con los saldos
del WMS por SKU y bodega, usando el código de bodega de Defontana registrado en cada
bodega del WMS (``erp_storage_code``). Solo informativo: no modifica ningún saldo.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.tenant_db import tenant_db
from app.core.utils import page, to_object_id
from app.models import Collections

_EPSILON = 1e-9


async def compare(
    tenant_id: str,
    *,
    only_diff: bool = True,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)

    snapshot = await db[Collections.ERP_STOCK].find({}).to_list(length=100000)
    snapshot_at = max((s["synced_at"] for s in snapshot if s.get("synced_at")), default=None)

    warehouses = await db[Collections.WAREHOUSES].find({}).to_list(length=1000)
    code_by_warehouse = {str(w["_id"]): w.get("erp_storage_code") for w in warehouses}
    name_by_warehouse = {str(w["_id"]): w.get("name") for w in warehouses}
    names_by_code = {w.get("erp_storage_code"): w.get("name") for w in warehouses if w.get("erp_storage_code")}

    products = await db[Collections.PRODUCTS].find({}, {"sku": 1, "name": 1}).to_list(length=100000)
    sku_by_product = {str(p["_id"]): p.get("sku") for p in products}
    name_by_sku = {p.get("sku"): p.get("name") for p in products}

    # Stock físico del WMS por (sku, bodega de Defontana): todas las ubicaciones, porque la
    # mercadería en staging/packing sigue en la bodega hasta que se despacha.
    wms: Dict[Tuple[str, str], float] = {}
    unmapped = set()
    async for balance in db[Collections.INVENTORY_BALANCES].find({}):
        qty = balance.get("quantity_on_hand") or 0
        sku = sku_by_product.get(balance.get("product_id"))
        if not qty or not sku:
            continue
        code = code_by_warehouse.get(balance.get("warehouse_id"))
        if not code:
            unmapped.add(balance.get("warehouse_id"))
            continue
        wms[(sku, code)] = wms.get((sku, code), 0) + qty

    lots: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    async for lot in db[Collections.ERP_BATCHES].find({}):
        key = (lot.get("sku"), lot.get("storage_code"))
        lots.setdefault(key, []).append({
            "lot_number": lot.get("lot_number"),
            "stock": lot.get("stock"),
            "expiration_date": lot.get("expiration_date"),
        })

    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in snapshot:
        key = (item.get("sku"), item.get("storage_code"))
        rows[key] = {
            "sku": key[0],
            "storage_code": key[1],
            "name": name_by_sku.get(key[0]) or item.get("name"),
            "erp_stock": item.get("erp_stock") or 0,
            "erp_reserved": item.get("erp_reserved") or 0,
            "erp_to_receive": item.get("erp_to_receive") or 0,
        }
    for key in wms:
        rows.setdefault(key, {
            "sku": key[0], "storage_code": key[1], "name": name_by_sku.get(key[0]),
            "erp_stock": None, "erp_reserved": None, "erp_to_receive": None,
        })

    result: List[Dict[str, Any]] = []
    for key, row in rows.items():
        wms_stock = wms.get(key, 0)
        erp_stock = row["erp_stock"]
        row.update({
            "wms_stock": wms_stock,
            "difference": wms_stock - (erp_stock or 0),
            "in_erp": erp_stock is not None,
            "in_wms_catalog": key[0] in name_by_sku,
            "erp_lots": sorted(
                lots.get(key, []),
                key=lambda l: (l["expiration_date"] is None, l["expiration_date"] or 0),
            ),
        })
        result.append(row)

    summary = {
        "rows": len(result),
        "with_difference": sum(1 for r in result if abs(r["difference"]) > _EPSILON),
        "erp_only": sum(1 for r in result if r["in_erp"] and not r["wms_stock"] and r["erp_stock"]),
        "wms_only": sum(1 for r in result if not r["in_erp"] and r["wms_stock"]),
        "snapshot_at": snapshot_at,
        "unmapped_warehouses": sorted(
            name_by_warehouse.get(w) or w for w in unmapped if w is not None
        ),
        # Bodegas del WMS con stock cuyo código no aparece en la foto de Defontana (p. ej. un
        # "01" de demo frente a "BODEGACENTRAL"): el stock queda partido en dos filas por SKU.
        "unknown_storage_codes": sorted(
            f"{names_by_code.get(code) or code} ({code})"
            for code in {key[1] for key in wms} - {item.get("storage_code") for item in snapshot}
        ) if snapshot else [],
    }

    if only_diff:
        result = [r for r in result if abs(r["difference"]) > _EPSILON]
    if q:
        needle = q.strip().lower()
        result = [
            r for r in result
            if needle in (r["sku"] or "").lower() or needle in (r["name"] or "").lower()
        ]
    result.sort(key=lambda r: (-abs(r["difference"]), r["sku"] or ""))

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return {**page(result[offset: offset + limit], len(result), limit, offset), "summary": summary}
