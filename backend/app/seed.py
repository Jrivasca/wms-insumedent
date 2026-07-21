"""Initial demo seed (section 14).

Idempotent: running it again will not duplicate the demo tenant.
Creates: Demo Company tenant, admin user, BODEGA CENTRAL warehouse with
locations, and the INSUMEDENT dental catalog (real Defontana export, in-stock
items only) with barcodes + real initial stock, plus demo order 1001.

The product catalog lives in ``app/data/demo_catalog.json`` (generated from the
depurated Defontana export) and is bulk-inserted for speed.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from app.core.database import get_database
from app.core.security import hash_password
from app.core.utils import now_utc
from app.models import Collections
from app.models.inventory import MovementType, ReferenceType
from app.models.location import LocationType
from app.models.order import OrderLineStatus, OrderStatus
from app.models.tenant import TenantStatus
from app.models.user import UserRole
from app.models.warehouse import WarehouseType
from app.services.warehouse_service import _create_default_locations

DEMO_TENANT_NAME = "Demo Company"
DEMO_ADMIN_EMAIL = "admin@demo.cl"
DEMO_ADMIN_PASSWORD = "admin123"

CATALOG_PATH = Path(__file__).parent / "data" / "demo_catalog.json"


def _load_catalog() -> List[Dict[str, Any]]:
    """Load the demo product catalog (in-stock INSUMEDENT items)."""
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


async def run_seed() -> Dict[str, Any]:
    db = get_database()
    now = now_utc()

    existing = await db[Collections.TENANTS].find_one({"name": DEMO_TENANT_NAME})
    if existing:
        return {
            "status": "already_seeded",
            "tenant_id": str(existing["_id"]),
            "admin_email": DEMO_ADMIN_EMAIL,
        }

    # --- Tenant ---
    tenant_result = await db[Collections.TENANTS].insert_one(
        {
            "name": DEMO_TENANT_NAME,
            "legal_code": "76.123.456-7",
            "email": "contacto@demo.cl",
            "status": TenantStatus.ACTIVE.value,
            "settings": {},
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    tenant_id = str(tenant_result.inserted_id)
    actor = "seed"

    # --- Warehouse + locations ---
    wh_result = await db[Collections.WAREHOUSES].insert_one(
        {
            "tenant_id": tenant_id,
            "erp_storage_code": "01",
            "name": "BODEGA CENTRAL",
            "description": "Bodega principal demo",
            "type": WarehouseType.WMS_WAREHOUSE.value,
            "sale_available": True,
            "is_active": True,
            "raw_erp_data": None,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
        }
    )
    warehouse_id = str(wh_result.inserted_id)
    await _create_default_locations(tenant_id, warehouse_id, actor)

    # Picking locations A-01-01 / A-01-02 (stock is spread across both).
    picking_codes = ("A-01-01", "A-01-02")
    picking_locations = {}
    for code in picking_codes:
        loc_result = await db[Collections.LOCATIONS].insert_one(
            {
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
                "code": code,
                "name": code,
                "zone": "A",
                "aisle": "01",
                "rack": code.split("-")[-1],
                "level": None,
                "bin": None,
                "type": LocationType.STORAGE.value,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
            }
        )
        picking_locations[code] = str(loc_result.inserted_id)

    # --- Admin user ---
    await db[Collections.USERS].insert_one(
        {
            "tenant_id": tenant_id,
            "name": "Administrador Demo",
            "email": DEMO_ADMIN_EMAIL,
            "password_hash": hash_password(DEMO_ADMIN_PASSWORD),
            "role": UserRole.ADMIN.value,
            "allowed_warehouse_ids": [warehouse_id],
            "is_active": True,
            "last_login_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
        }
    )

    # --- Products + barcodes + initial stock (bulk) ---
    catalog = _load_catalog()

    product_docs = []
    for item in catalog:
        product_docs.append(
            {
                "tenant_id": tenant_id,
                "erp_product_id": f"ERP-{item['sku']}",
                "sku": item["sku"],
                "name": item["name"],
                "description": item.get("description") or item["name"],
                "unit": "UN",
                "brand": None,
                "category": item["category"],
                "uses_lots": False,
                "uses_serials": False,
                "is_service": False,
                "is_active": True,
                # Pricing from the Defontana export (kept as metadata).
                "cost": item.get("cost"),
                "sale_price": item.get("sale_price"),
                "raw_erp_data": None,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
            }
        )
    product_result = await db[Collections.PRODUCTS].insert_many(product_docs)
    product_ids = {
        item["sku"]: str(oid)
        for item, oid in zip(catalog, product_result.inserted_ids)
    }

    barcode_docs = []
    balance_docs = []
    movement_docs = []
    for idx, item in enumerate(catalog):
        product_id = product_ids[item["sku"]]
        # Spread stock across the two picking locations round-robin.
        location_id = picking_locations[picking_codes[idx % len(picking_codes)]]
        qty = item["stock"]

        barcode_docs.append(
            {
                "tenant_id": tenant_id,
                "product_id": product_id,
                "barcode": item["barcode"],
                "type": "ean13",
                "source": "manual",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        balance_docs.append(
            {
                "tenant_id": tenant_id,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "location_id": location_id,
                "lot_number": None,
                "serial_number": None,
                "quantity_on_hand": qty,
                "quantity_reserved": 0,
                "quantity_blocked": 0,
                "quantity_available": qty,
                "updated_at": now,
            }
        )
        movement_docs.append(
            {
                "tenant_id": tenant_id,
                "movement_type": MovementType.RECEIPT.value,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "from_location_id": None,
                "to_location_id": location_id,
                "quantity": qty,
                "lot_number": None,
                "serial_number": None,
                "reference_type": ReferenceType.MANUAL.value,
                "reference_id": None,
                "reason": "Carga inicial catálogo",
                "created_by": actor,
                "created_at": now,
            }
        )

    if barcode_docs:
        await db[Collections.BARCODES].insert_many(barcode_docs)
    if balance_docs:
        await db[Collections.INVENTORY_BALANCES].insert_many(balance_docs)
    if movement_docs:
        await db[Collections.INVENTORY_MOVEMENTS].insert_many(movement_docs)

    # --- Demo orders (varied real products so the full flow can be practiced) ---
    def _line(n: int, item: Dict[str, Any], qty: int) -> Dict[str, Any]:
        return {
            "line_id": f"L{n}",
            "product_id": product_ids[item["sku"]],
            "sku": item["sku"],
            "name": item["name"],
            "unit": "UN",
            "ordered_quantity": min(qty, item["stock"]),
            "picked_quantity": 0,
            "packed_quantity": 0,
            "status": OrderLineStatus.PENDING.value,
        }

    # Order 1001 keeps the first two catalog products (consistent with the
    # Defontana mock). The others pull products spread across the catalog so the
    # demo shows several categories and there is always something to pick.
    spread = [it for it in catalog[2:] if it["stock"] >= 6]
    step = max(1, len(spread) // 12)
    picks = [spread[i] for i in range(0, len(spread), step)]

    order_specs = [
        ("1001", "Clínica Dental Demo SPA", [(catalog[0], 5), (catalog[1], 3)]),
    ]
    if len(picks) >= 9:
        order_specs += [
            ("1002", "Centro Odontológico Los Andes", [(picks[0], 2), (picks[1], 4), (picks[2], 1)]),
            ("1003", "Dental Norte Ltda.", [(picks[3], 6), (picks[4], 2)]),
            ("1004", "Clínica Sonrisa Feliz", [(picks[5], 3)]),
            ("1005", "OdontoSalud SpA", [(picks[6], 2), (picks[7], 2), (picks[8], 5)]),
        ]

    order_docs = []
    for number, customer, lines_spec in order_specs:
        order_docs.append(
            {
                "tenant_id": tenant_id,
                "erp_order_number": number,
                "erp_document_id": f"DOC-{number}",
                "customer": customer,
                "status": OrderStatus.IMPORTED.value,
                "order_date": now,
                "delivery_date": None,
                "warehouse_id": warehouse_id,
                "lines": [_line(n, it, q) for n, (it, q) in enumerate(lines_spec, start=1)],
                "raw_erp_data": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
            }
        )
    await db[Collections.ORDERS].insert_many(order_docs)

    return {
        "status": "seeded",
        "tenant_id": tenant_id,
        "admin_email": DEMO_ADMIN_EMAIL,
        "admin_password": DEMO_ADMIN_PASSWORD,
        "warehouse_id": warehouse_id,
        "products": len(catalog),
        "total_stock_units": sum(i["stock"] for i in catalog),
        "orders": [s[0] for s in order_specs],
    }
