"""Excel catalog importer (Plan 1, Fase 2).

Replaces the Defontana ``sync_products`` pull: the product master is exported from
the ERP to an ``.xlsx`` and imported here (manual upload or folder-watch). Rules:

- headers are matched by name (accent/case-insensitive synonyms); the **code (SKU)
  column is mandatory**;
- **all-or-nothing**: if any row is missing its SKU the whole file is rejected and
  nothing is written;
- otherwise every row is upserted by ``(tenant, sku)`` and its barcode added if new.

Also keeps a per-tenant last-import timestamp so a "no lo cargaste en 24 h" reminder
can fire (``catalog_staleness_check``).
"""
import io
import unicodedata
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook

from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.models.notification import NotificationType
from app.models.product import BarcodeSource, BarcodeType
from app.services import notification_service

logger = get_logger(__name__)

# Recognized header synonyms (normalized: lowercased, accent-stripped, trimmed).
_HEADER_SYNONYMS: Dict[str, set] = {
    "sku": {"codigo", "code", "sku", "cod", "cod producto", "codigo producto", "cod. producto"},
    "name": {"nombre", "name", "descripcion", "detalle", "glosa", "producto"},
    "barcode": {"codigo de barras", "barcode", "ean", "ean13", "cod barra", "codigo barra",
                "cod de barras", "codigo de barra"},
    "category": {"categoria", "familia", "family", "rubro", "linea"},
    "unit": {"unidad", "unit", "um", "u.m.", "u. m."},
    "cost": {"costo", "cost", "costo neto"},
    "sale_price": {"precio", "precio venta", "price", "sale price", "precio de venta", "valor"},
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(" ", "")
    # Chilean formatting: "1.234,50" -> 1234.50
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _map_headers(row: Tuple) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for idx, cell in enumerate(row):
        norm = _norm(cell)
        if not norm:
            continue
        for field, syns in _HEADER_SYNONYMS.items():
            if norm in syns and field not in mapping.values():
                mapping[idx] = field
                break
    return mapping


def _parse(data: bytes) -> Tuple[bool, Dict[int, str], List[Tuple]]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    header_map: Dict[int, str] = {}
    header_found = False
    data_rows: List[Tuple] = []
    for row in ws.iter_rows(values_only=True):
        if not header_found:
            candidate = _map_headers(row)
            if "sku" in candidate.values():
                header_map = candidate
                header_found = True
            continue
        data_rows.append(row)
    wb.close()
    return header_found, header_map, data_rows


async def import_xlsx(tenant_id: str, data: bytes, actor: str, source: str = "upload") -> Dict[str, Any]:
    """Parse and upsert the catalog. Returns a report; never partially applies."""
    try:
        header_found, header_map, rows = _parse(data)
    except Exception as exc:  # noqa: BLE001 - archivo corrupto / no es xlsx
        return {"applied": False, "rows": 0, "error": f"No se pudo leer el Excel: {exc}"}

    if not header_found:
        return {"applied": False, "rows": 0,
                "error": "No se encontró la columna de código (SKU) en el Excel."}

    records: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        rec: Dict[str, Any] = {}
        for idx, field in header_map.items():
            rec[field] = row[idx] if idx < len(row) else None
        if not any(v not in (None, "") for v in rec.values()):
            continue  # fila vacía
        sku = str(rec.get("sku")).strip() if rec.get("sku") not in (None, "") else ""
        if not sku:
            rejected.append({"row": i, "reason": "Sin código (SKU)"})
            continue
        rec["sku"] = sku
        records.append(rec)

    if rejected:
        return {"applied": False, "rows": len(records) + len(rejected), "rejected": rejected,
                "error": f"{len(rejected)} fila(s) sin código; no se aplicó ningún cambio."}
    if not records:
        return {"applied": False, "rows": 0, "error": "El Excel no tiene filas de productos."}

    db = tenant_db(tenant_id)
    now = now_utc()
    created = updated = barcodes_added = 0
    for rec in records:
        outcome, product_id = await _upsert_product(db, tenant_id, rec, actor, now)
        created += outcome == "created"
        updated += outcome == "updated"
        barcode = rec.get("barcode")
        if barcode not in (None, ""):
            if await _add_barcode(db, tenant_id, product_id, str(barcode).strip(), actor, now):
                barcodes_added += 1

    report = {"applied": True, "rows": len(records), "created": created,
              "updated": updated, "barcodes_added": barcodes_added, "rejected": []}
    await _record_import(db, source, report)
    return report


async def _upsert_product(db, tenant_id: str, rec: Dict[str, Any], actor: str, now) -> Tuple[str, str]:
    sku = rec["sku"]
    existing = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": sku})
    name = str(rec["name"]).strip() if rec.get("name") not in (None, "") else (
        (existing or {}).get("name") or sku
    )
    doc: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "sku": sku,
        "name": name,
        "category": (str(rec["category"]).strip() if rec.get("category") not in (None, "")
                     else (existing or {}).get("category") or "Sin categoría"),
        "unit": (str(rec["unit"]).strip() if rec.get("unit") not in (None, "")
                 else (existing or {}).get("unit") or "UN"),
        "is_active": True,
        "updated_at": now,
        "updated_by": actor,
    }
    if _num(rec.get("cost")) is not None:
        doc["cost"] = _num(rec.get("cost"))
    if _num(rec.get("sale_price")) is not None:
        doc["sale_price"] = _num(rec.get("sale_price"))

    if existing:
        await db[Collections.PRODUCTS].update_one({"_id": existing["_id"]}, {"$set": doc})
        return "updated", str(existing["_id"])

    doc.update({
        "erp_product_id": f"WMS-{sku}",
        "description": name,
        "brand": None,
        "uses_lots": False,
        "uses_serials": False,
        "is_service": False,
        "created_at": now,
        "created_by": actor,
    })
    result = await db[Collections.PRODUCTS].insert_one(doc)
    return "created", str(result.inserted_id)


async def _add_barcode(db, tenant_id: str, product_id: str, barcode: str, actor: str, now) -> bool:
    if not barcode:
        return False
    existing = await db[Collections.BARCODES].find_one({"tenant_id": tenant_id, "barcode": barcode})
    if existing:
        return False
    bc_type = (
        BarcodeType.EAN13.value if barcode.isdigit() and len(barcode) == 13
        else BarcodeType.SUPPLIER.value
    )
    await db[Collections.BARCODES].insert_one({
        "tenant_id": tenant_id,
        "product_id": product_id,
        "barcode": barcode,
        "type": bc_type,
        "source": BarcodeSource.MANUAL.value,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
    })
    return True


# ---------------------------------------------------------------------------
# Staleness reminder ("no lo cargaste en 24 h")
# ---------------------------------------------------------------------------
def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _record_import(db, source: str, report: Dict[str, Any]) -> None:
    await db[Collections.CATALOG_IMPORT_STATE].update_one(
        {},
        {"$set": {"last_import_at": now_utc(), "last_source": source, "last_report": report}},
        upsert=True,
    )


async def catalog_staleness_check(tenant_id: str, max_age_hours: int = 24) -> bool:
    """Emit a reminder if the catalog hasn't been imported within ``max_age_hours``.
    Deduped to at most one alert per window. Returns whether it alerted."""
    db = tenant_db(tenant_id)
    now = now_utc()
    state = await db[Collections.CATALOG_IMPORT_STATE].find_one({})
    last_import = _aware(state.get("last_import_at")) if state else None
    if last_import and (now - last_import) <= timedelta(hours=max_age_hours):
        return False
    last_alert = _aware(state.get("last_stale_alert_at")) if state else None
    if last_alert and (now - last_alert) < timedelta(hours=max_age_hours):
        return False
    await db[Collections.CATALOG_IMPORT_STATE].update_one(
        {}, {"$set": {"last_stale_alert_at": now}}, upsert=True
    )
    await notification_service.emit(
        tenant_id=tenant_id,
        notification_type=NotificationType.CATALOG_IMPORT.value,
        title="Catálogo sin actualizar",
        body=f"No se importó el catálogo en las últimas {max_age_hours} h.",
        entity_type="product",
    )
    return True
