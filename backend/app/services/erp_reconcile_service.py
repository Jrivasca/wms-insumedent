"""Conciliación WMS ← Defontana.

Defontana manda las cantidades (ver `docs/entregables/Modelo-de-stock-con-Defontana.md`): la
conciliación calcula qué hay que ajustar en el WMS para que su stock coincida con la última foto
del ERP (``erp_stock``), usando los lotes que informa Defontana (``erp_batches``) para lo que
falta y FEFO para lo que sobra.

- ``preview`` solo calcula: no escribe nada.
- ``apply`` escribe esos ajustes en el WMS, con un movimiento de conciliación auditable por cada
  uno. **Nunca viajan a Defontana**: el ERP ya tiene esas cantidades y reenviarlas con
  ``Inventory/Insert`` las duplicaría. Por eso usa los ayudantes de bajo nivel del inventario y
  no ``create_adjustment``, que encola el envío.

Las diferencias de más de ``DEFONTANA_RECONCILE_REVIEW_UNITS`` quedan para revisión humana: la
corrida automática no las toca y un supervisor las aprueba una por una.

Ambas funciones comparten el mismo cálculo (``_rows``): lo que se ve en la vista previa es
exactamente lo que se aplica.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.utils import page
from app.integrations.defontana.schedule import local_now
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.location import LocationType
from app.services import inventory_service

_EPSILON = 1e-9
# Dónde queda lo que aparece de más en el ERP hasta que bodega lo ubique: primero una ubicación
# de recepción (no pickeable, así el picking no manda a buscar ahí antes de ubicarlo); si la
# bodega no tiene, se mantiene el comportamiento anterior.
_INBOUND_LOCATION_TYPES = (
    LocationType.RECEIVING.value,
    LocationType.STORAGE.value,
    LocationType.STAGING.value,
)


def _fefo_key(balance: Dict[str, Any]) -> Tuple[int, Any, str]:
    """Primero lo que vence antes; lo sin vencimiento al final."""
    expiration = balance.get("expiration_date")
    return (1 if expiration is None else 0, expiration or 0, balance.get("location_id") or "")


def _aware_utc(value: datetime) -> datetime:
    """Motor devuelve fechas sin zona horaria (en UTC)."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _inbound_location(db, warehouse_id: str) -> Optional[Dict[str, Any]]:
    """Ubicación donde dejar lo que falta: la configurada (``SIN-UBICAR``) o, si no existe,
    la primera de recepción, almacenamiento o staging, en ese orden."""
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


async def snapshot_taken_at(tenant_id: str) -> Optional[datetime]:
    """Cuándo se tomó la foto de stock del ERP que usa la conciliación (None si no hay)."""
    latest = await (
        tenant_db(tenant_id)[Collections.ERP_STOCK]
        .find({"synced_at": {"$ne": None}})
        .sort("synced_at", -1)
        .limit(1)
        .to_list(length=1)
    )
    return latest[0]["synced_at"] if latest else None


async def _rows(db) -> Tuple[List[Dict[str, Any]], Optional[datetime]]:
    """Filas con diferencia y las acciones que la resolverían. Compartido por la vista previa y
    la aplicación."""
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
            "product_id": str(product["_id"]) if product else None,
            "warehouse_id": str(warehouse["_id"]),
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
                            "serial_number": None,
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
                            "serial_number": None,
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
                    # La llave del saldo incluye la serie: sin ella, el descuento buscaría un
                    # saldo que no existe y fallaría por stock negativo.
                    "serial_number": balance.get("serial_number"),
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
    threshold = settings.defontana_reconcile_review_units
    for row in rows:
        for action in row["actions"]:
            # Si la ubicación ya no existe, mostrar su identificador en vez de dejarlo vacío.
            action["location_code"] = (
                action["location_code"] or codes.get(action["location_id"]) or action["location_id"]
            )
        # Solo se revisa lo que se podría aplicar: lo bloqueado no se aplica nunca.
        row["needs_review"] = (
            bool(row["actions"]) and not row["blocked"] and abs(row["difference"]) > threshold
        )

    return rows, snapshot_at


async def preview(
    tenant_id: str, *, q: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    rows, snapshot_at = await _rows(tenant_db(tenant_id))

    summary = {
        "rows": len(rows),
        "to_add": sum(1 for r in rows if r["difference"] > 0),
        "to_remove": sum(1 for r in rows if r["difference"] < 0),
        "units_to_add": sum(a["quantity"] for r in rows for a in r["actions"] if a["type"] == "add"),
        "units_to_remove": sum(a["quantity"] for r in rows for a in r["actions"] if a["type"] == "remove"),
        "blocked": sum(1 for r in rows if r["blocked"]),
        # Lo que la corrida automática aplicaría sola, y lo que espera a un supervisor.
        "auto": sum(1 for r in rows if r["actions"] and not r["blocked"] and not r["needs_review"]),
        "to_review": sum(1 for r in rows if r["needs_review"]),
        "review_units": settings.defontana_reconcile_review_units,
        "snapshot_at": snapshot_at,
    }

    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in (r["sku"] or "").lower() or needle in (r["name"] or "").lower()]
    rows.sort(key=lambda r: (-abs(r["difference"]), r["sku"] or ""))

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return {**page(rows[offset: offset + limit], len(rows), limit, offset), "summary": summary}


def _snapshot_label(snapshot_at: Optional[datetime]) -> str:
    if not snapshot_at:
        return ""
    local = _aware_utc(snapshot_at).astimezone(local_now().tzinfo)
    return f" (foto del {local.strftime('%d-%m-%Y %H:%M')})"


async def apply(
    tenant_id: str,
    actor: str,
    *,
    keys: Optional[Iterable[Tuple[str, str]]] = None,
    include_review: bool = False,
) -> Dict[str, Any]:
    """Aplica al WMS los ajustes de la conciliación, sin enviar nada a Defontana.

    Sin ``keys`` (corrida diaria o botón general) aplica solo las diferencias chicas: las que
    superan el umbral quedan para revisión humana. Con ``keys`` aplica esas filas puntuales
    ``(sku, código de bodega)``; con ``include_review`` también si son grandes: es la aprobación
    de un supervisor, fila por fila.

    Una fila que falla (por ejemplo, porque el stock cambió desde que se calculó) queda en
    ``errors`` y no frena al resto; lo que alcanzó a aplicarse deja su movimiento, y la próxima
    corrida resuelve la diferencia que quede.
    """
    db = tenant_db(tenant_id)
    rows, snapshot_at = await _rows(db)
    wanted = {tuple(k) for k in keys} if keys is not None else None
    reason = f"Conciliación con Defontana{_snapshot_label(snapshot_at)}"

    result: Dict[str, Any] = {
        "applied": 0, "units_added": 0.0, "units_removed": 0.0,
        "skipped_review": 0, "skipped_blocked": 0, "errors": [],
    }
    applied_keys = set()
    for row in rows:
        key = (row["sku"], row["storage_code"])
        if wanted is not None and key not in wanted:
            continue
        if row["blocked"] or not row["actions"]:
            result["skipped_blocked"] += 1
            continue
        if row["needs_review"] and not include_review:
            result["skipped_review"] += 1
            continue
        try:
            for action in row["actions"]:
                adding = action["type"] == "add"
                await inventory_service.change_location_stock(
                    tenant_id=tenant_id,
                    product_id=row["product_id"],
                    warehouse_id=row["warehouse_id"],
                    location_id=action["location_id"],
                    delta=action["quantity"] if adding else -action["quantity"],
                    lot_number=action["lot_number"],
                    serial_number=action["serial_number"],
                    expiration_date=action["expiration_date"] if adding else None,
                    notify=False,
                )
                await inventory_service.record_movement(
                    tenant_id=tenant_id,
                    movement_type=MovementType.RECONCILIATION.value,
                    product_id=row["product_id"],
                    warehouse_id=row["warehouse_id"],
                    quantity=action["quantity"],
                    to_location_id=action["location_id"] if adding else None,
                    from_location_id=None if adding else action["location_id"],
                    lot_number=action["lot_number"],
                    serial_number=action["serial_number"],
                    reference_type=ReferenceType.RECONCILIATION.value,
                    reason=reason,
                    created_by=actor,
                )
                result["units_added" if adding else "units_removed"] += action["quantity"]
            applied_keys.add(key)
            result["applied"] += 1
        except Exception as exc:  # noqa: BLE001 - una fila no debe frenar al resto
            result["errors"].append({
                "sku": row["sku"],
                "storage_code": row["storage_code"],
                "error": str(getattr(exc, "detail", exc))[:200],
            })

    result["pending_review"] = sum(
        1 for r in rows if r["needs_review"] and (r["sku"], r["storage_code"]) not in applied_keys
    )
    result["snapshot_at"] = snapshot_at
    return result
