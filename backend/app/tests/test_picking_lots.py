"""Elegir lote al pickear (opción b): la lista de lotes sale del stock pickeable ordenada FEFO,
elegir lote es obligatorio para productos que manejan lotes, y el pick descuenta el lote elegido
y lo lleva a staging con su vencimiento (para que el lote viaje hasta la guía de despacho)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.seed import run_seed
from app.services import order_service, picking_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio


def _picker(tenant_id):
    return make_user({"_id": "picker-1", "tenant_id": tenant_id, "role": "picker"})


async def _setup():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    db = tenant_db(tenant_id)
    warehouse = await db[Collections.WAREHOUSES].find_one({})
    warehouse_id = str(warehouse["_id"])
    storage = await db[Collections.LOCATIONS].find_one(
        {"warehouse_id": warehouse_id, "type": "storage"})
    loc_id = str(storage["_id"])

    base = await get_database()[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    bl = base["lines"][0]
    product_id = bl["product_id"]

    # Sembrar dos lotes con distinto vencimiento en la ubicación pickeable (y limpiar el resto).
    await db[Collections.INVENTORY_BALANCES].delete_many({"product_id": product_id})

    async def _bal(lot, exp, qty):
        await db[Collections.INVENTORY_BALANCES].insert_one({
            "tenant_id": tenant_id, "product_id": product_id, "warehouse_id": warehouse_id,
            "location_id": loc_id, "lot_number": lot, "serial_number": None,
            "expiration_date": exp, "quantity_on_hand": qty, "quantity_available": qty,
            "quantity_reserved": 0, "quantity_blocked": 0,
            "updated_at": datetime.now(timezone.utc),
        })

    await _bal("LOTE-B", datetime(2026, 12, 31, tzinfo=timezone.utc), 5)  # vence antes
    await _bal("LOTE-A", datetime(2028, 6, 30, tzinfo=timezone.utc), 5)

    order = await order_service.create_order_from_lines(
        tenant_id=tenant_id, erp_order_number="9101", customer="Test",
        lines=[SimpleNamespace(sku=bl["sku"], name=bl.get("name"), unit=bl.get("unit", "UN"),
                               ordered_quantity=3, product_id=product_id)],
        created_by="tester")
    picker = _picker(tenant_id)
    task = await order_service.create_picking_task(tenant_id, order["id"], picker.id)
    bc = (await db[Collections.BARCODES].find_one({"product_id": product_id}))["barcode"]
    return SimpleNamespace(
        tenant_id=tenant_id, warehouse_id=warehouse_id, product_id=product_id, loc_id=loc_id,
        task_id=task["id"], line_id=task["lines"][0]["line_id"], picker=picker, bc=bc, db=db)


async def test_available_lots_are_fefo_and_lote_is_required():
    s = await _setup()
    res = await picking_service.available_lots(s.tenant_id, s.task_id, s.line_id, s.picker)
    assert res["manages_lots"] is True
    # FEFO: el que vence antes (LOTE-B) va primero.
    assert [l["lot_number"] for l in res["lots"]] == ["LOTE-B", "LOTE-A"]
    assert res["lots"][0]["quantity_available"] == 5
    # Sin elegir lote, el escaneo se rechaza (no se confirma sin lote).
    rej = await picking_service.scan(s.tenant_id, s.task_id, s.picker, s.bc, 3, None, None)
    assert rej["status"] == "rejected" and "lote" in rej["message"].lower()


async def test_pick_decrements_the_chosen_lote_and_carries_it_to_staging():
    s = await _setup()
    ok = await picking_service.scan(s.tenant_id, s.task_id, s.picker, s.bc, 3, s.loc_id, "LOTE-B")
    assert ok["status"] == "ok"
    scan = ok["line"]["scans"][-1]
    assert scan["lot_number"] == "LOTE-B" and scan["quantity"] == 3

    await picking_service.complete(s.tenant_id, s.task_id, s.picker)

    # LOTE-B bajó a 2; LOTE-A quedó intacto en 5.
    b = await s.db[Collections.INVENTORY_BALANCES].find_one(
        {"product_id": s.product_id, "location_id": s.loc_id, "lot_number": "LOTE-B"})
    a = await s.db[Collections.INVENTORY_BALANCES].find_one(
        {"product_id": s.product_id, "location_id": s.loc_id, "lot_number": "LOTE-A"})
    assert b["quantity_on_hand"] == 2 and a["quantity_on_hand"] == 5

    # Staging recibió el lote elegido, con su vencimiento (para viajar a la guía).
    staging = await s.db[Collections.LOCATIONS].find_one(
        {"warehouse_id": s.warehouse_id, "type": "staging"})
    st = await s.db[Collections.INVENTORY_BALANCES].find_one(
        {"product_id": s.product_id, "location_id": str(staging["_id"]), "lot_number": "LOTE-B"})
    assert st and st["quantity_on_hand"] == 3 and st.get("expiration_date") is not None

    # El movimiento de pick registró el lote.
    mv = await s.db[Collections.INVENTORY_MOVEMENTS].find_one(
        {"product_id": s.product_id, "movement_type": "pick", "lot_number": "LOTE-B"})
    assert mv is not None


async def test_a_lote_without_pickable_stock_is_rejected():
    s = await _setup()
    # Un lote que no tiene saldo pickeable no se puede elegir (invita a actualizar desde Defontana).
    rej = await picking_service.scan(s.tenant_id, s.task_id, s.picker, s.bc, 3, s.loc_id, "NO-EXISTE")
    assert rej["status"] == "rejected" and "lote" in rej["message"].lower()
