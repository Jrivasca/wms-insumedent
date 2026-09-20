"""Ubicar stock: mover un saldo EXACTO a otra ubicación de la misma bodega.

Es la operación que sigue a la conciliación, que deja todo lo nuevo en SIN-UBICAR, donde no
se puede pickear. Como el saldo llega identificado (lote, serie y vencimiento son los de esa
fila), no hay forma de mover el saldo equivocado ni de perder la fecha de vencimiento.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.services import inventory_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio

VENCE = datetime(2027, 3, 1, tzinfo=timezone.utc)


async def _tenant(name="T"):
    r = await get_database()[Collections.TENANTS].insert_one({"name": name, "is_active": True})
    tenant_id = str(r.inserted_id)
    db = tenant_db(tenant_id)
    warehouse = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})).inserted_id)
    locations = {}
    for code, loc_type in (("SIN-UBICAR", "receiving"), ("A-01", "storage"),
                           ("A-02", "storage"), ("STAGING", "staging"),
                           ("VIEJA", "storage")):
        locations[code] = str((await db[Collections.LOCATIONS].insert_one(
            {"warehouse_id": warehouse, "code": code, "type": loc_type,
             "is_active": code != "VIEJA"})).inserted_id)
    user = make_user({"_id": "u-1", "tenant_id": tenant_id, "role": "admin"})
    return tenant_id, db, warehouse, locations, user


async def _product(db, sku="SKU-1", barcode=None):
    pid = str((await db[Collections.PRODUCTS].insert_one(
        {"sku": sku, "name": f"Producto {sku}"})).inserted_id)
    if barcode:
        await db[Collections.BARCODES].insert_one({"product_id": pid, "barcode": barcode})
    return pid


async def _balance(db, tenant_id, product_id, warehouse_id, location_id, qty,
                   lot=None, serial=None, expiration=None, reserved=0):
    r = await db[Collections.INVENTORY_BALANCES].insert_one({
        "tenant_id": tenant_id, "product_id": product_id, "warehouse_id": warehouse_id,
        "location_id": location_id, "lot_number": lot, "serial_number": serial,
        "quantity_on_hand": qty, "quantity_reserved": reserved, "quantity_blocked": 0,
        "quantity_available": qty - reserved, "expiration_date": expiration,
    })
    return str(r.inserted_id)


async def _row(db, product_id, location_id, lot=None):
    return await db[Collections.INVENTORY_BALANCES].find_one(
        {"product_id": product_id, "location_id": location_id, "lot_number": lot})


# ---------------------------------------------------------------------------
async def test_putaway_keeps_lot_and_expiry_at_the_destination():
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    # Dos lotes del mismo producto en SIN-UBICAR: el saldo exacto evita mover el equivocado.
    bid = await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 10, lot="L1",
                         expiration=VENCE)
    await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 5, lot="L2",
                   expiration=VENCE + timedelta(days=365))

    result = await inventory_service.putaway(
        tenant_id=tenant_id, balance_id=bid, to_location_id=loc["A-01"], quantity=4, user=user)

    destino = await _row(db, pid, loc["A-01"], lot="L1")
    assert destino["quantity_on_hand"] == 4
    # Mongo devuelve la fecha sin zona horaria (guarda UTC): se compara el instante.
    assert destino["expiration_date"].replace(tzinfo=timezone.utc) == VENCE  # si no, se cae del FEFO
    assert (await _row(db, pid, loc["SIN-UBICAR"], lot="L1"))["quantity_on_hand"] == 6
    assert (await _row(db, pid, loc["SIN-UBICAR"], lot="L2"))["quantity_on_hand"] == 5  # intacto
    assert result["to_location_code"] == "A-01"

    movimiento = await db[Collections.INVENTORY_MOVEMENTS].find_one({"movement_type": "transfer"})
    assert movimiento["from_location_id"] == loc["SIN-UBICAR"]
    assert movimiento["to_location_id"] == loc["A-01"]
    assert movimiento["lot_number"] == "L1" and movimiento["quantity"] == 4
    # Mover entre ubicaciones es asunto del WMS: el ERP no se entera.
    assert await db[Collections.SYNC_JOBS].count_documents({}) == 0


async def test_putaway_without_lot():
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    bid = await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 7)

    await inventory_service.putaway(
        tenant_id=tenant_id, balance_id=bid, to_location_id=loc["A-01"], quantity=7, user=user)

    assert (await _row(db, pid, loc["A-01"]))["quantity_on_hand"] == 7
    assert (await _row(db, pid, loc["SIN-UBICAR"]))["quantity_on_hand"] == 0


async def test_putaway_refuses_more_than_available():
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    bid = await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 3)

    with pytest.raises(HTTPException) as exc:
        await inventory_service.putaway(
            tenant_id=tenant_id, balance_id=bid, to_location_id=loc["A-01"], quantity=4, user=user)
    assert exc.value.status_code == 409
    assert (await _row(db, pid, loc["SIN-UBICAR"]))["quantity_on_hand"] == 3  # nada se movió


async def test_putaway_refuses_another_warehouse_an_inactive_location_and_the_same_place():
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    bid = await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 5)
    otra_bodega = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "OTRA", "erp_storage_code": "OTRA"})).inserted_id)
    ajena = str((await db[Collections.LOCATIONS].insert_one(
        {"warehouse_id": otra_bodega, "code": "B-01", "type": "storage"})).inserted_id)

    for destino, code in ((ajena, 400), (loc["VIEJA"], 400), (loc["SIN-UBICAR"], 400)):
        with pytest.raises(HTTPException) as exc:
            await inventory_service.putaway(
                tenant_id=tenant_id, balance_id=bid, to_location_id=destino, quantity=1, user=user)
        assert exc.value.status_code == code
    assert (await _row(db, pid, loc["SIN-UBICAR"]))["quantity_on_hand"] == 5


async def test_putaway_does_not_touch_goods_being_prepared():
    """Lo que está en STAGING ya es de un pedido en preparación: no se reubica."""
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    bid = await _balance(db, tenant_id, pid, wh, loc["STAGING"], 6)

    with pytest.raises(HTTPException) as exc:
        await inventory_service.putaway(
            tenant_id=tenant_id, balance_id=bid, to_location_id=loc["A-01"], quantity=1, user=user)
    assert exc.value.status_code == 409
    assert (await _row(db, pid, loc["STAGING"]))["quantity_on_hand"] == 6


async def test_putaway_cannot_reach_another_tenant_balance():
    tenant_a, db_a, wh_a, loc_a, user_a = await _tenant("A")
    tenant_b, db_b, wh_b, loc_b, _ = await _tenant("B")
    pid_b = await _product(db_b)
    ajeno = await _balance(db_b, tenant_b, pid_b, wh_b, loc_b["SIN-UBICAR"], 9)

    with pytest.raises(HTTPException) as exc:
        await inventory_service.putaway(
            tenant_id=tenant_a, balance_id=ajeno, to_location_id=loc_a["A-01"],
            quantity=1, user=user_a)
    assert exc.value.status_code == 404
    assert (await _row(db_b, pid_b, loc_b["SIN-UBICAR"]))["quantity_on_hand"] == 9


# --- consulta de saldos: búsqueda y paginación reales -----------------------
async def test_balances_search_runs_on_the_server_across_every_page():
    tenant_id, db, wh, loc, user = await _tenant()
    aguja = await _product(db, "SKU-AGUJA", barcode="7800000000017")
    otro = await _product(db, "SKU-OTRO")
    await _balance(db, tenant_id, aguja, wh, loc["SIN-UBICAR"], 4, lot="LOTE-X")
    for i in range(60):  # relleno: la aguja queda fuera de la primera página
        await _balance(db, tenant_id, otro, wh, loc["SIN-UBICAR"], 1, serial=f"S{i:03d}")

    por_sku = await inventory_service.list_balances(tenant_id, user=user, q="AGUJA")
    por_lote = await inventory_service.list_balances(tenant_id, user=user, q="lote-x")
    por_barra = await inventory_service.list_balances(tenant_id, user=user, q="7800000000017")
    for resultado in (por_sku, por_lote, por_barra):
        assert resultado["total"] == 1
        assert resultado["items"][0]["sku"] == "SKU-AGUJA"

    # Paginación estable: dos páginas sin repetir ni perder filas.
    p1 = await inventory_service.list_balances(tenant_id, user=user, limit=25, offset=0)
    p2 = await inventory_service.list_balances(tenant_id, user=user, limit=25, offset=25)
    assert p1["total"] == 61
    ids = [b["id"] for b in p1["items"]] + [b["id"] for b in p2["items"]]
    assert len(set(ids)) == 50


async def test_balances_hide_empty_rows_by_default():
    tenant_id, db, wh, loc, user = await _tenant()
    pid = await _product(db)
    await _balance(db, tenant_id, pid, wh, loc["SIN-UBICAR"], 0)
    await _balance(db, tenant_id, pid, wh, loc["A-01"], 2)

    assert (await inventory_service.list_balances(tenant_id, user=user))["total"] == 1
    todos = await inventory_service.list_balances(tenant_id, user=user, positive_only=False)
    assert todos["total"] == 2


async def test_balances_of_a_forbidden_warehouse_return_an_empty_page():
    """Antes devolvía una lista en vez de la página: la vista se rompía en vez de salir vacía."""
    tenant_id, db, wh, loc, _ = await _tenant()
    limitado = make_user({"_id": "u-2", "tenant_id": tenant_id, "role": "picker",
                          "allowed_warehouse_ids": ["otra-bodega"]})
    pid = await _product(db)
    await _balance(db, tenant_id, pid, wh, loc["A-01"], 5)

    resultado = await inventory_service.list_balances(tenant_id, warehouse_id=wh, user=limitado)
    assert resultado == {"items": [], "total": 0, "limit": 100, "offset": 0}
