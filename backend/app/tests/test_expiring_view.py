"""Vista de vencido y por vencer (horizonte 180 días).

Es independiente del aviso automático: el worker notifica a 30 días y una sola vez por lote
(``check_expiring_stock``); esta consulta mira más lejos y se puede pedir cuando se quiera.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.services import inventory_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio


def _en(dias: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=dias)


async def _setup():
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    tenant_id = str(r.inserted_id)
    db = tenant_db(tenant_id)
    warehouse = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})).inserted_id)
    locations = {}
    for code, tipo in (("A-01", "storage"), ("QUARANTINE", "quarantine")):
        locations[code] = str((await db[Collections.LOCATIONS].insert_one(
            {"warehouse_id": warehouse, "code": code, "type": tipo})).inserted_id)
    user = make_user({"_id": "u-1", "tenant_id": tenant_id, "role": "admin"})
    return tenant_id, db, warehouse, locations, user


async def _producto(db, sku):
    return str((await db[Collections.PRODUCTS].insert_one(
        {"sku": sku, "name": f"Producto {sku}"})).inserted_id)


async def _saldo(db, tenant_id, product_id, warehouse_id, location_id, qty,
                 lot=None, expiration=None):
    await db[Collections.INVENTORY_BALANCES].insert_one({
        "tenant_id": tenant_id, "product_id": product_id, "warehouse_id": warehouse_id,
        "location_id": location_id, "lot_number": lot, "serial_number": None,
        "quantity_on_hand": qty, "quantity_reserved": 0, "quantity_blocked": 0,
        "quantity_available": qty, "expiration_date": expiration,
    })


async def _poblar(db, tenant_id, warehouse, loc):
    """Un saldo por tramo, más dos que la vista debe ignorar."""
    datos = [
        ("VENCIDO", -10, 5, "L-VENC"),
        ("PRONTO", 15, 3, "L-30"),
        ("MEDIO", 60, 7, "L-90"),
        ("LEJANO", 150, 2, "L-180"),
        ("MUY-LEJANO", 300, 9, "L-300"),   # fuera del horizonte de 180 días
    ]
    for sku, dias, qty, lote in datos:
        await _saldo(db, tenant_id, await _producto(db, sku), warehouse, loc["A-01"], qty,
                     lot=lote, expiration=_en(dias))
    # Sin unidades: no hay nada que hacer con él.
    await _saldo(db, tenant_id, await _producto(db, "EN-CERO"), warehouse, loc["A-01"], 0,
                 lot="L-0", expiration=_en(5))
    # Sin fecha: no se puede clasificar.
    await _saldo(db, tenant_id, await _producto(db, "SIN-FECHA"), warehouse, loc["A-01"], 4)


# ---------------------------------------------------------------------------
async def test_the_four_buckets_and_what_stays_out():
    tenant_id, db, warehouse, loc, user = await _setup()
    await _poblar(db, tenant_id, warehouse, loc)

    result = await inventory_service.expiring_stock(tenant_id, user=user)

    assert [i["sku"] for i in result["items"]] == ["VENCIDO", "PRONTO", "MEDIO", "LEJANO"]  # FEFO
    assert [i["bucket"] for i in result["items"]] == ["expired", "d30", "d90", "d180"]
    assert result["items"][0]["days_left"] < 0
    assert result["summary"]["rows"] == 4  # fuera: el de 300 días, el de cero y el sin fecha
    assert result["summary"]["units"] == 17
    assert {k: v["rows"] for k, v in result["summary"]["buckets"].items()} == {
        "expired": 1, "d30": 1, "d90": 1, "d180": 1}
    assert result["summary"]["buckets"]["expired"]["units"] == 5


async def test_a_shorter_horizon_narrows_it():
    tenant_id, db, warehouse, loc, user = await _setup()
    await _poblar(db, tenant_id, warehouse, loc)

    result = await inventory_service.expiring_stock(tenant_id, user=user, days=30)

    assert [i["sku"] for i in result["items"]] == ["VENCIDO", "PRONTO"]
    assert result["summary"]["buckets"]["d90"]["rows"] == 0


async def test_search_and_filters():
    tenant_id, db, warehouse, loc, user = await _setup()
    await _poblar(db, tenant_id, warehouse, loc)
    producto = await _producto(db, "CUARENTENA")
    await _saldo(db, tenant_id, producto, warehouse, loc["QUARANTINE"], 6,
                 lot="L-Q", expiration=_en(20))

    por_sku = await inventory_service.expiring_stock(tenant_id, user=user, q="MEDIO")
    por_lote = await inventory_service.expiring_stock(tenant_id, user=user, q="l-venc")
    por_ubicacion = await inventory_service.expiring_stock(
        tenant_id, user=user, location_id=loc["QUARANTINE"])

    assert [i["sku"] for i in por_sku["items"]] == ["MEDIO"]
    assert por_sku["summary"]["rows"] == 1  # el resumen respeta el filtro
    assert [i["sku"] for i in por_lote["items"]] == ["VENCIDO"]
    assert [i["sku"] for i in por_ubicacion["items"]] == ["CUARENTENA"]
    assert por_ubicacion["items"][0]["location_code"] == "QUARANTINE"
    assert por_ubicacion["items"][0]["location_type"] == "quarantine"


async def test_pagination_keeps_fefo_order_across_pages():
    tenant_id, db, warehouse, loc, user = await _setup()
    producto = await _producto(db, "MULTILOTE")
    for dias in range(1, 61):
        await _saldo(db, tenant_id, producto, warehouse, loc["A-01"], 1,
                     lot=f"L{dias:03d}", expiration=_en(dias))

    p1 = await inventory_service.expiring_stock(tenant_id, user=user, limit=25, offset=0)
    p2 = await inventory_service.expiring_stock(tenant_id, user=user, limit=25, offset=25)

    assert p1["total"] == 60
    lotes = [i["lot_number"] for i in p1["items"]] + [i["lot_number"] for i in p2["items"]]
    assert len(set(lotes)) == 50
    assert lotes == sorted(lotes)  # sigue siendo FEFO entre páginas


async def test_another_warehouse_is_not_visible_to_a_scoped_user():
    tenant_id, db, warehouse, loc, user = await _setup()
    await _poblar(db, tenant_id, warehouse, loc)
    limitado = make_user({"_id": "u-2", "tenant_id": tenant_id, "role": "picker",
                          "allowed_warehouse_ids": ["otra-bodega"]})

    propio = await inventory_service.expiring_stock(tenant_id, user=limitado)
    pedido = await inventory_service.expiring_stock(
        tenant_id, user=limitado, warehouse_id=warehouse)

    assert propio["total"] == 0 and propio["summary"]["rows"] == 0
    assert pedido["total"] == 0 and pedido["items"] == []
