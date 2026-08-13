"""Lotes y vencimiento (Plan 1, Fase 5): la recepción guarda el vencimiento en el
saldo, el picking sugiere FEFO (lote de vencimiento más próximo), y el chequeo de
"por vencer" alerta una vez por lote dentro de la ventana."""
from datetime import timedelta

import pytest
from bson import ObjectId

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.services import inventory_service
from app.services.order_service import _suggested_location

pytestmark = pytest.mark.asyncio


async def _product(tenant_id: str, sku="SKU1") -> str:
    db = get_database()
    r = await db[Collections.PRODUCTS].insert_one({"tenant_id": tenant_id, "sku": sku, "name": "Prod"})
    return str(r.inserted_id)


async def _receive(tenant_id, pid, wid, loc, qty, lot, days):
    await inventory_service.create_reception(
        tenant_id=tenant_id, product_id=pid, warehouse_id=wid, location_id=loc,
        quantity=qty, created_by="u1", lot_number=lot,
        expiration_date=now_utc() + timedelta(days=days), sync_erp=False,
    )


# ---------------------------------------------------------------------------
async def test_reception_stores_expiration_on_balance():
    tid = "tA"
    pid = await _product(tid)
    await _receive(tid, pid, "wh1", "locA", 5, "L1", 40)
    bal = await tenant_db(tid)[Collections.INVENTORY_BALANCES].find_one({"product_id": pid})
    assert bal["expiration_date"] is not None
    assert bal["quantity_on_hand"] == 5


async def test_picking_suggests_nearest_expiry_location_fefo():
    tid = "tA"
    pid = await _product(tid)
    await _receive(tid, pid, "wh1", "locFar", 5, "L-far", 60)
    await _receive(tid, pid, "wh1", "locNear", 5, "L-near", 10)
    # FEFO: la ubicación del lote que vence antes.
    assert await _suggested_location(tid, pid, "wh1") == "locNear"


async def test_expiring_check_alerts_once_and_respects_window():
    tid = "tA"
    pid = await _product(tid)
    # Un lote dentro de la ventana (10 d) y otro fuera (60 d).
    await _receive(tid, pid, "wh1", "locA", 5, "L-soon", 10)
    await _receive(tid, pid, "wh1", "locB", 5, "L-later", 60)

    alerted = await inventory_service.check_expiring_stock(tid, days=30)
    assert alerted == 1  # solo el lote que vence dentro de 30 d
    # Deduplicado.
    assert await inventory_service.check_expiring_stock(tid, days=30) == 0


async def test_expiring_check_ignores_lots_without_stock():
    tid = "tA"
    pid = await _product(tid)
    # Saldo con vencimiento próximo pero sin stock -> no alerta.
    db = tenant_db(tid)
    await db[Collections.INVENTORY_BALANCES].insert_one({
        "product_id": pid, "warehouse_id": "wh1", "location_id": "locA",
        "lot_number": "L0", "serial_number": None,
        "quantity_on_hand": 0, "expiration_date": now_utc() + timedelta(days=5),
    })
    assert await inventory_service.check_expiring_stock(tid, days=30) == 0


async def test_expiring_check_is_tenant_isolated():
    a, b = "tA", "tB"
    pid = await _product(a)
    await _receive(a, pid, "wh1", "locA", 5, "L1", 10)
    assert await inventory_service.check_expiring_stock(b, days=30) == 0
    assert await inventory_service.check_expiring_stock(a, days=30) == 1
