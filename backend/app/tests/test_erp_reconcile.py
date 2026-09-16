"""Conciliación WMS ← Defontana en vista previa: qué se sumaría (con los lotes del ERP) y qué
se descontaría (por FEFO) para que el WMS coincida con el ERP. No debe escribir nada."""
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.services import erp_reconcile_service

pytestmark = pytest.mark.asyncio

VENCE_PRONTO = datetime(2026, 10, 31, tzinfo=timezone.utc)
VENCE_LEJOS = datetime(2028, 12, 31, tzinfo=timezone.utc)


async def _setup():
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    tenant_id = str(r.inserted_id)
    db = tenant_db(tenant_id)
    warehouse = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})).inserted_id)
    await db[Collections.LOCATIONS].insert_one(
        {"warehouse_id": warehouse, "code": "STAGING", "type": "staging"})
    await db[Collections.LOCATIONS].insert_one(
        {"warehouse_id": warehouse, "code": "A-01", "type": "storage"})
    return tenant_id, db, warehouse


async def _product(db, sku, name):
    return str((await db[Collections.PRODUCTS].insert_one({"sku": sku, "name": name})).inserted_id)


async def _balance(db, product_id, warehouse_id, location, qty, lot=None, expiration=None):
    await db[Collections.INVENTORY_BALANCES].insert_one({
        "product_id": product_id, "warehouse_id": warehouse_id, "location_id": location,
        "quantity_on_hand": qty, "lot_number": lot, "expiration_date": expiration})


async def _erp_stock(db, sku, qty):
    await db[Collections.ERP_STOCK].insert_one({
        "sku": sku, "storage_code": "BODEGACENTRAL", "erp_stock": qty,
        "synced_at": datetime.now(timezone.utc)})


# ---------------------------------------------------------------------------
async def test_missing_stock_is_added_using_the_erp_lots_and_does_not_write():
    tenant_id, db, warehouse = await _setup()
    product = await _product(db, "A", "Alcohol gel")
    await _balance(db, product, warehouse, "A-01", 4, lot="L1", expiration=VENCE_LEJOS)
    await _erp_stock(db, "A", 10)
    for lot, stock, expiration in (("L1", 6, VENCE_LEJOS), ("L2", 3, VENCE_PRONTO)):
        await db[Collections.ERP_BATCHES].insert_one({
            "sku": "A", "storage_code": "BODEGACENTRAL", "lot_number": lot, "stock": stock,
            "expiration_date": expiration})

    result = await erp_reconcile_service.preview(tenant_id)

    row = result["items"][0]
    assert row["erp_stock"] == 10 and row["wms_stock"] == 4 and row["difference"] == 6
    # Primero el lote que vence antes; L1 solo aporta lo que falta (6 en el ERP - 4 en el WMS).
    assert [(a["lot_number"], a["quantity"], a["location_code"]) for a in row["actions"]] == [
        ("L2", 3, "A-01"), ("L1", 2, "A-01"), (None, 1, "A-01")
    ]
    assert all(a["type"] == "add" for a in row["actions"])
    assert row["actions"][0]["expiration_date"].date() == VENCE_PRONTO.date()
    assert result["summary"]["to_add"] == 1 and result["summary"]["units_to_add"] == 6

    # Vista previa: nada cambió en el WMS.
    assert await db[Collections.INVENTORY_BALANCES].count_documents({}) == 1
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 0


async def test_surplus_is_removed_by_fefo():
    tenant_id, db, warehouse = await _setup()
    product = await _product(db, "B", "Bisturí")
    await _balance(db, product, warehouse, "A-01", 3, lot="LEJOS", expiration=VENCE_LEJOS)
    await _balance(db, product, warehouse, "STAGING", 2, lot="PRONTO", expiration=VENCE_PRONTO)
    await _erp_stock(db, "B", 1)

    row = (await erp_reconcile_service.preview(tenant_id))["items"][0]

    assert row["difference"] == -4
    # FEFO: primero el que vence antes (2), luego el otro (2 de 3).
    assert [(a["lot_number"], a["quantity"], a["location_code"]) for a in row["actions"]] == [
        ("PRONTO", 2, "STAGING"), ("LEJOS", 2, "A-01")
    ]
    assert all(a["type"] == "remove" for a in row["actions"])


async def test_a_warehouse_code_missing_in_defontana_is_never_emptied():
    """Si el código de bodega del WMS no existe en Defontana, el ERP no está diciendo "0": está
    mal configurada. Proponer vaciarla borraría el stock real."""
    tenant_id, db, warehouse = await _setup()
    demo = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA DEMO", "erp_storage_code": "01"})).inserted_id)
    product = await _product(db, "A", "Alcohol gel")
    await _balance(db, product, demo, "loc-demo", 500)
    await _erp_stock(db, "A", 500)  # el ERP informa BODEGACENTRAL, no "01"

    row = next(r for r in (await erp_reconcile_service.preview(tenant_id))["items"]
               if r["storage_code"] == "01")

    assert row["actions"] == [] and "no existe en Defontana" in row["blocked"]


async def test_blocked_rows_are_flagged_instead_of_inventing_a_location(monkeypatch):
    tenant_id, db, warehouse = await _setup()
    await _erp_stock(db, "SIN-CATALOGO", 5)  # existe en el ERP pero no en el WMS
    otra = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA SIN UBICACIONES", "erp_storage_code": "B2"})).inserted_id)
    await _product(db, "C", "Cemento")
    await db[Collections.ERP_STOCK].insert_one({
        "sku": "C", "storage_code": "B2", "erp_stock": 5, "synced_at": datetime.now(timezone.utc)})

    result = await erp_reconcile_service.preview(tenant_id)
    blocked = {r["sku"]: r["blocked"] for r in result["items"]}

    assert "catálogo" in blocked["SIN-CATALOGO"]
    assert "ubicación" in blocked["C"]
    assert all(not r["actions"] for r in result["items"])
    assert result["summary"]["blocked"] == 2
    assert otra  # la bodega existe, pero sin ubicaciones no se puede proponer dónde dejarlo


async def test_configured_inbound_location_is_used(monkeypatch):
    monkeypatch.setattr(settings, "defontana_reconcile_location_code", "STAGING")
    tenant_id, db, warehouse = await _setup()
    await _product(db, "D", "Dique")
    await _erp_stock(db, "D", 2)

    row = (await erp_reconcile_service.preview(tenant_id))["items"][0]

    assert [(a["location_code"], a["quantity"]) for a in row["actions"]] == [("STAGING", 2)]
