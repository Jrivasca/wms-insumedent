"""Conciliación WMS ← Defontana (por ahora, solo vista previa).

Defontana manda las cantidades (ver `docs/entregables/Modelo-de-stock-con-Defontana.md`):
esta conciliación calcula qué habría que ajustar en el WMS para que su stock coincida con la
última foto del ERP (``erp_stock``), usando los lotes que informa Defontana (``erp_batches``)
para lo que falta y FEFO para lo que sobra.

**Solo calcula: no escribe saldos ni movimientos.** Cuando se implemente el "aplicar", esos
ajustes NO deben viajar a Defontana con ``Inventory/Insert``: el ERP ya tiene esas cantidades y
volver a enviarlas las duplicaría.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.utils import page
from app.models import Collections
from app.models.location import LocationType

_EPSILON = 1e-9
# Dónde queda lo que aparece de más en el ERP hasta que bodega lo ubique.
_INBOUND_LOCATION_TYPES = (LocationType.STORAGE.value, LocationType.STAGING.value)


def _fefo_key(balance: Dict[str, Any]) -> Tuple[int, Any, str]:
    """Primero lo que vence antes; lo sin vencimiento al final."""
    expiration = balance.get("expiration_date")
    return (1 if expiration is None else 0, expiration or 0, balance.get("location_id") or "")


async def _inbound_location(db, warehouse_id: str) -> Optional[Dict[str, Any]]:
    """Ubicación donde dejar lo que falta: la configurada, o la primera de almacenamiento."""
    if settings.defontana_reconcile_location_code:
        located = await db[Collections.LOCATIONS].find_one(
            {"warehouse_id": warehouse_id, "code": settings.defontana_reconcile_location_code}
        )
        if located:
            return located
    for location_type in _INBOUND_LOCATION_TYPES:
        located = await db[Collections.LOCATIONS].find_one(
            {"warehouse_id": warehouse_id, "type": location_type}
        )
        if located:
            return located
    return None


async def preview(
    tenant_id: str, *, q: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)

    snapshot = await db[Collections.ERP_STOCK].find({}).to_list(length=100000)
    snapshot_at = max((s["synced_at"] for s in snapshot if s.get("synced_at")), default=None)

    warehouses = await db[Collections.WAREHOUSES].find({}).to_list(length=1000)
    warehouse_by_code = {w.get("erp_storage_code"): w for w in warehouses if w.get("erp_storage_code")}
    code_by_warehouse = {str(w["_id"]): w.get("erp_storage_code") for w in warehouses}

    products = await db[Collections.PRODUCTS].find({}, {"sku": 1, "name": 1}).to_list(length=100000)
    product_by_sku = {p.get("sku"): p for p in products}

    balances_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    sku_by_product = {str(p["_id"]): p.get("sku") for p in products}
    async for balance in db[Collections.INVENTORY_BALANCES].find({}):
        sku = sku_by_product.get(balance.get("product_id"))
        code = code_by_warehouse.get(balance.get("warehouse_id"))
        if not sku or not code or not (balance.get("quantity_on_hand") or 0):
            continue
        balances_by_key.setdefault((sku, code), []).append(balance)

    lots_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    async for lot in db[Collections.ERP_BATCHES].find({}):
        lots_by_key.setdefault((lot.get("sku"), lot.get("storage_code")), []).append(lot)

    erp_by_key = {(s.get("sku"), s.get("storage_code")): (s.get("erp_stock") or 0) for s in snapshot}
    # Códigos de bodega que Defontana informó: si el código del WMS no está entre ellos, no es
    # que el ERP tenga 0, es que la bodega está mal configurada. Nunca proponer vaciarla.
    erp_codes = {s.get("storage_code") for s in snapshot}
    location_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    rows: List[Dict[str, Any]] = []

    for key in set(erp_by_key) | set(balances_by_key):
        sku, code = key
        warehouse = warehouse_by_code.get(code)
        if not warehouse:
            continue  # bodega del ERP que el WMS no tiene: se ve en el informe de diferencias
        erp_stock = erp_by_key.get(key, 0)
        balances = balances_by_key.get(key, [])
        wms_stock = sum(b.get("quantity_on_hand") or 0 for b in balances)
        difference = erp_stock - wms_stock
        if abs(difference) <= _EPSILON:
            continue

        product = product_by_sku.get(sku)
        row = {
            "sku": sku,
            "name": (product or {}).get("name"),
            "storage_code": code,
            "warehouse_name": warehouse.get("name"),
            "erp_stock": erp_stock,
            "wms_stock": wms_stock,
            "difference": difference,
            "actions": [],
            "blocked": None,
        }

        if code not in erp_codes:
            row["blocked"] = (
                f"El código de bodega «{code}» no existe en Defontana: revisa la bodega en el WMS"
            )
        elif difference > 0:  # falta en el WMS: sumar, respetando los lotes del ERP
            if not product:
                row["blocked"] = "El producto no está en el catálogo del WMS"
            else:
                warehouse_id = str(warehouse["_id"])
                if warehouse_id not in location_cache:
                    location_cache[warehouse_id] = await _inbound_location(db, warehouse_id)
                location = location_cache[warehouse_id]
                if not location:
                    row["blocked"] = "La bodega no tiene ubicación de entrada"
                else:
                    pending = difference
                    wms_by_lot: Dict[Optional[str], float] = {}
                    for balance in balances:
                        wms_by_lot[balance.get("lot_number")] = (
                            wms_by_lot.get(balance.get("lot_number"), 0)
                            + (balance.get("quantity_on_hand") or 0)
                        )
                    for lot in sorted(
                        lots_by_key.get(key, []),
                        key=lambda l: (l.get("expiration_date") is None, l.get("expiration_date") or 0),
                    ):
                        gap = (lot.get("stock") or 0) - wms_by_lot.get(lot.get("lot_number"), 0)
                        quantity = min(gap, pending)
                        if quantity <= _EPSILON:
                            continue
                        row["actions"].append({
                            "type": "add",
                            "location_id": str(location["_id"]),
                            "location_code": location.get("code"),
                            "lot_number": lot.get("lot_number"),
                            "expiration_date": lot.get("expiration_date"),
                            "quantity": quantity,
                        })
                        pending -= quantity
                    if pending > _EPSILON:  # el resto, sin lote identificado
                        row["actions"].append({
                            "type": "add",
                            "location_id": str(location["_id"]),
                            "location_code": location.get("code"),
                            "lot_number": None,
                            "expiration_date": None,
                            "quantity": pending,
                        })
        elif difference < 0:  # sobra en el WMS: descontar por FEFO
            pending = -difference
            for balance in sorted(balances, key=_fefo_key):
                if pending <= _EPSILON:
                    break
                quantity = min(balance.get("quantity_on_hand") or 0, pending)
                row["actions"].append({
                    "type": "remove",
                    "location_id": balance.get("location_id"),
                    "location_code": None,
                    "lot_number": balance.get("lot_number"),
                    "expiration_date": balance.get("expiration_date"),
                    "quantity": quantity,
                })
                pending -= quantity

        rows.append(row)

    # Nombre de ubicación para las líneas de descuento (las de suma ya lo traen).
    location_ids = {a["location_id"] for r in rows for a in r["actions"] if a["location_id"]}
    codes = {}
    async for location in db[Collections.LOCATIONS].find({}):
        if str(location["_id"]) in location_ids:
            codes[str(location["_id"])] = location.get("code")
    for row in rows:
        for action in row["actions"]:
            # Si la ubicación ya no existe, mostrar su identificador en vez de dejarlo vacío.
            action["location_code"] = (
                action["location_code"] or codes.get(action["location_id"]) or action["location_id"]
            )

    summary = {
        "rows": len(rows),
        "to_add": sum(1 for r in rows if r["difference"] > 0),
        "to_remove": sum(1 for r in rows if r["difference"] < 0),
        "units_to_add": sum(a["quantity"] for r in rows for a in r["actions"] if a["type"] == "add"),
        "units_to_remove": sum(a["quantity"] for r in rows for a in r["actions"] if a["type"] == "remove"),
        "blocked": sum(1 for r in rows if r["blocked"]),
        "snapshot_at": snapshot_at,
    }

    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in (r["sku"] or "").lower() or needle in (r["name"] or "").lower()]
    rows.sort(key=lambda r: (-abs(r["difference"]), r["sku"] or ""))

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return {**page(rows[offset: offset + limit], len(rows), limit, offset), "summary": summary}
