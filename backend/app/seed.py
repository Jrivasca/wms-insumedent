"""Initial demo seed (section 14).

Idempotent: running it again will not duplicate the demo tenant.
Creates: Demo Company tenant, admin user, BODEGA CENTRAL warehouse with
locations, 3 demo products with barcodes + initial stock, and demo order 1001.
"""
from typing import Any, Dict

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
from app.services import inventory_service
from app.services.warehouse_service import _create_default_locations

DEMO_TENANT_NAME = "Demo Company"
DEMO_ADMIN_EMAIL = "admin@demo.cl"
DEMO_ADMIN_PASSWORD = "admin123"

DEMO_PRODUCTS = [
    {"sku": "SKU001", "name": "Polera Deportiva", "barcode": "780000000001"},
    {"sku": "SKU002", "name": "Zapatilla Training", "barcode": "780000000002"},
    {"sku": "SKU003", "name": "Botella Deportiva", "barcode": "780000000003"},
]


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

    # Picking locations A-01-01 / A-01-02
    picking_locations = {}
    for code in ("A-01-01", "A-01-02"):
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

    # --- Products + barcodes + initial stock ---
    product_ids = {}
    default_location = picking_locations["A-01-01"]
    for item in DEMO_PRODUCTS:
        p_result = await db[Collections.PRODUCTS].insert_one(
            {
                "tenant_id": tenant_id,
                "erp_product_id": f"ERP-{item['sku']}",
                "sku": item["sku"],
                "name": item["name"],
                "description": item["name"],
                "unit": "UN",
                "brand": "GenericSport",
                "category": "Demo",
                "uses_lots": False,
                "uses_serials": False,
                "is_service": False,
                "is_active": True,
                "raw_erp_data": None,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
            }
        )
        product_id = str(p_result.inserted_id)
        product_ids[item["sku"]] = product_id

        await db[Collections.BARCODES].insert_one(
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

        # Initial stock via a traceable receipt movement.
        await inventory_service.change_location_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=default_location,
            delta=100,
            allow_negative=True,
        )
        await inventory_service.record_movement(
            tenant_id=tenant_id,
            movement_type=MovementType.RECEIPT.value,
            product_id=product_id,
            warehouse_id=warehouse_id,
            to_location_id=default_location,
            quantity=100,
            reference_type=ReferenceType.MANUAL.value,
            reason="Seed inicial",
            created_by=actor,
        )

    # --- Demo order 1001 ---
    await db[Collections.ORDERS].insert_one(
        {
            "tenant_id": tenant_id,
            "erp_order_number": "1001",
            "erp_document_id": "DOC-1001",
            "customer": "Cliente Demo SPA",
            "status": OrderStatus.IMPORTED.value,
            "order_date": now,
            "delivery_date": None,
            "warehouse_id": warehouse_id,
            "lines": [
                {
                    "line_id": "L1",
                    "product_id": product_ids["SKU001"],
                    "sku": "SKU001",
                    "name": "Polera Deportiva",
                    "unit": "UN",
                    "ordered_quantity": 3,
                    "picked_quantity": 0,
                    "packed_quantity": 0,
                    "status": OrderLineStatus.PENDING.value,
                },
                {
                    "line_id": "L2",
                    "product_id": product_ids["SKU002"],
                    "sku": "SKU002",
                    "name": "Zapatilla Training",
                    "unit": "UN",
                    "ordered_quantity": 2,
                    "picked_quantity": 0,
                    "packed_quantity": 0,
                    "status": OrderLineStatus.PENDING.value,
                },
            ],
            "raw_erp_data": None,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
        }
    )

    return {
        "status": "seeded",
        "tenant_id": tenant_id,
        "admin_email": DEMO_ADMIN_EMAIL,
        "admin_password": DEMO_ADMIN_PASSWORD,
        "warehouse_id": warehouse_id,
        "products": list(product_ids.keys()),
        "order": "1001",
    }
