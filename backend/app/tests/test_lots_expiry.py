"""Lotes y vencimiento (Plan 1, Fase 5): la recepción guarda el vencimiento en el
saldo, el picking sugiere FEFO (lote de vencimiento más próximo), y el chequeo de
"por vencer" alerta una vez por lote dentro de la ventana."""
from datetime import timedelta

import pytest
from bson import ObjectId

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.services import inventory_service
from app.services.order_service import _suggested_location
from app.tests.conftest import crear_referencias

pytestmark = pytest.mark.asyncio


async def _refs(tenant_id: str, *locations: str) -> dict:
    """Producto, bodega y ubicaciones reales: la recepción valida que existan."""
    return await crear_referencias(tenant_id, locations=locations or ("A-01",))


async def _receive(tenant_id, pid, wid, loc, qty, lot, days):
    await inventory_service.create_reception(
        tenant_id=tenant_id, product_id=pid, warehouse_id=wid, location_id=loc,
        quantity=qty, created_by="u1", lot_number=lot,
        expiration_date=now_utc() + timedelta(days=days), sync_erp=False,
    )


# ---------------------------------------------------------------------------
async def test_reception_stores_expiration_on_balance():
    tid = "tA"
    r = await _refs(tid, "A-01")
    pid = r["product_id"]
    await _receive(tid, pid, r["warehouse_id"], r["A-01"], 5, "L1", 40)
    bal = await tenant_db(tid)[Collections.INVENTORY_BALANCES].find_one({"product_id": pid})
    assert bal["expiration_date"] is not None
    assert bal["quantity_on_hand"] == 5


async def test_picking_suggests_nearest_expiry_location_fefo():
    tid = "tA"
    r = await _refs(tid, "LEJOS", "CERCA")
    pid, wid = r["product_id"], r["warehouse_id"]
    await _receive(tid, pid, wid, r["LEJOS"], 5, "L-far", 60)
    await _receive(tid, pid, wid, r["CERCA"], 5, "L-near", 10)
    # FEFO: la ubicación del lote que vence antes.
    assert await _suggested_location(tid, pid, wid) == r["CERCA"]


async def test_picking_never_suggests_non_pickable_locations_even_if_they_expire_first():
    """Lo que está en staging (ya es de otro pedido) o sin ubicar (recepción) no se pickea,
    aunque su lote venza antes. Antes FEFO podía mandar al operario a buscarlo ahí."""
    tid = "tA"
    ids = await _refs(tid, "STAGING", "SIN-UBICAR", "A-01")
    pid, wid = ids["product_id"], ids["warehouse_id"]
    db = tenant_db(tid)
    for code, loc_type in (("STAGING", "staging"), ("SIN-UBICAR", "receiving")):
        await db[Collections.LOCATIONS].update_one(
            {"_id": to_object_id(ids[code])}, {"$set": {"type": loc_type}})
    await _receive(tid, pid, wid, ids["STAGING"], 5, "L-staging", 5)
    await _receive(tid, pid, wid, ids["SIN-UBICAR"], 5, "L-sin-ubicar", 8)
    await _receive(tid, pid, wid, ids["A-01"], 5, "L-estante", 90)

    assert await _suggested_location(tid, pid, wid) == ids["A-01"]


async def test_non_pickable_exclusion_also_applies_to_stock_without_expiry():
    """La segunda búsqueda (stock sin vencimiento) tiene que excluir lo mismo que la de FEFO:
    corregir solo la primera dejaría pasar el mismo defecto por la otra."""
    tid = "tA"
    pid = (await _refs(tid))["product_id"]
    db = tenant_db(tid)
    staging = str((await db[Collections.LOCATIONS].insert_one(
        {"tenant_id": tid, "warehouse_id": "wh1", "code": "STAGING", "type": "staging"})).inserted_id)
    shelf = str((await db[Collections.LOCATIONS].insert_one(
        {"tenant_id": tid, "warehouse_id": "wh1", "code": "A-01", "type": "storage"})).inserted_id)
    # Staging primero en el orden de inserción: sin la exclusión, find_one lo devolvería a él.
    for location_id in (staging, shelf):
        await db[Collections.INVENTORY_BALANCES].insert_one({
            "tenant_id": tid, "product_id": pid, "warehouse_id": "wh1",
            "location_id": location_id, "lot_number": None, "serial_number": None,
            "quantity_on_hand": 3, "expiration_date": None,
        })

    assert await _suggested_location(tid, pid, "wh1") == shelf


async def test_expiring_check_alerts_once_and_respects_window():
    tid = "tA"
    r = await _refs(tid, "A-01", "A-02")
    pid, wid = r["product_id"], r["warehouse_id"]
    # Un lote dentro de la ventana (10 d) y otro fuera (60 d).
    await _receive(tid, pid, wid, r["A-01"], 5, "L-soon", 10)
    await _receive(tid, pid, wid, r["A-02"], 5, "L-later", 60)

    alerted = await inventory_service.check_expiring_stock(tid, days=30)
    assert alerted == 1  # solo el lote que vence dentro de 30 d
    # Deduplicado.
    assert await inventory_service.check_expiring_stock(tid, days=30) == 0


async def test_expiring_check_ignores_lots_without_stock():
    tid = "tA"
    pid = (await _refs(tid))["product_id"]
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
    r = await _refs(a, "A-01")
    pid = r["product_id"]
    await _receive(a, pid, r["warehouse_id"], r["A-01"], 5, "L1", 10)
    assert await inventory_service.check_expiring_stock(b, days=30) == 0
    assert await inventory_service.check_expiring_stock(a, days=30) == 1
