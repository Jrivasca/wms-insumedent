"""Foto de stock de Defontana (Inventory/GetFutureStockInfo) y su comparación con el stock
del WMS. Solo informativo: nada de esto mueve saldos. Sin red: se reemplaza ``_request``."""
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import client as client_module
from app.integrations.defontana import stock_sync
from app.integrations.defontana.client import DefontanaConnector
from app.models import Collections
from app.services import erp_stock_service

pytestmark = pytest.mark.asyncio


async def _tenant() -> str:
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    return str(r.inserted_id)


def _fake_api(monkeypatch, handler):
    calls = []

    async def fake_request(self, method, path, *, params=None, json=None):
        calls.append((method, path, dict(params or {})))
        return handler(method, path, params or {}, json)

    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(DefontanaConnector, "_request", fake_request)
    return calls


async def test_sync_erp_stock_reads_pages_from_one_and_replaces_the_snapshot(monkeypatch):
    monkeypatch.setattr(client_module, "PAGE_SIZE", 2)
    items = [
        {"productCode": f"P{i}", "description": f"Producto {i}", "currentStock": i,
         "storageInfo": [{"storageCode": "BODEGACENTRAL", "productCode": f"P{i}", "currentStock": i,
                          "reservedStock": 1, "maximumStockToReceive": 2, "maximumFutureStock": i + 1}]}
        for i in range(3)
    ]

    def handler(method, path, params, json):
        page = params["Page"]  # GetFutureStockInfo parte en la página 1
        return {"success": True, "totalItems": 3, "productsDetail": items[(page - 1) * 2: page * 2]}

    calls = _fake_api(monkeypatch, handler)
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    await db[Collections.ERP_CONNECTIONS].insert_one({"erp": "defontana", "status": "connected"})

    assert await stock_sync.sync_erp_stock(tenant_id) == {"products": 3, "rows": 3}
    assert [c[2]["Page"] for c in calls] == [1, 2]
    assert all(c[1] == "/Inventory/GetFutureStockInfo" and c[2]["ItemsPerPage"] == 2 for c in calls)
    row = await db[Collections.ERP_STOCK].find_one({"sku": "P2"})
    assert row["erp_stock"] == 2 and row["erp_reserved"] == 1 and row["erp_to_receive"] == 2
    assert (await db[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"}))["last_stock_sync_at"]

    await stock_sync.sync_erp_stock(tenant_id)  # la foto se reemplaza, no se duplica
    assert await db[Collections.ERP_STOCK].count_documents({}) == 3


async def test_comparison_warns_when_a_wms_warehouse_code_does_not_exist_in_defontana():
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    demo = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA DEMO", "erp_storage_code": "01"})).inserted_id)
    product = str((await db[Collections.PRODUCTS].insert_one({"sku": "A", "name": "Alcohol"})).inserted_id)
    await db[Collections.INVENTORY_BALANCES].insert_one(
        {"product_id": product, "warehouse_id": demo, "location_id": "L1", "quantity_on_hand": 5})
    await db[Collections.ERP_STOCK].insert_one(
        {"sku": "A", "storage_code": "BODEGACENTRAL", "erp_stock": 5, "synced_at": datetime.now(timezone.utc)})

    summary = (await erp_stock_service.compare(tenant_id, only_diff=False))["summary"]

    assert summary["unknown_storage_codes"] == ["BODEGA DEMO (01)"]
    assert summary["with_difference"] == 2  # el mismo SKU queda partido en dos bodegas


async def test_comparison_flags_differences_lots_and_unmapped_warehouses():
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    central = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})).inserted_id)
    sin_codigo = str((await db[Collections.WAREHOUSES].insert_one({"name": "BODEGA SIN CÓDIGO"})).inserted_id)

    async def product(sku, name):
        return str((await db[Collections.PRODUCTS].insert_one({"sku": sku, "name": name})).inserted_id)

    a, b, c, e = (await product("A", "Alcohol gel"), await product("B", "Bisturí"),
                  await product("C", "Cemento"), await product("E", "Eugenol"))

    async def balance(product_id, warehouse_id, location, qty):
        await db[Collections.INVENTORY_BALANCES].insert_one(
            {"product_id": product_id, "warehouse_id": warehouse_id, "location_id": location,
             "quantity_on_hand": qty})

    await balance(a, central, "L1", 3)
    await balance(a, central, "STAGING", 2)   # sigue en la bodega hasta despacharse
    await balance(b, central, "L1", 4)
    await balance(c, sin_codigo, "L1", 7)     # bodega sin código de Defontana: no se cruza
    await balance(e, central, "L1", 2)        # sin registro en Defontana

    now = datetime.now(timezone.utc)
    for sku, erp in (("A", 5), ("B", 1), ("D", 2)):
        await db[Collections.ERP_STOCK].insert_one(
            {"sku": sku, "name": f"ERP {sku}", "storage_code": "BODEGACENTRAL", "erp_stock": erp,
             "erp_reserved": 0, "erp_to_receive": 0, "synced_at": now})
    await db[Collections.ERP_BATCHES].insert_one(
        {"sku": "B", "storage_code": "BODEGACENTRAL", "lot_number": "L-1", "stock": 1,
         "expiration_date": datetime(2027, 1, 31, tzinfo=timezone.utc)})

    diff = await erp_stock_service.compare(tenant_id, only_diff=True)

    assert [(r["sku"], r["difference"]) for r in diff["items"]] == [("B", 3), ("D", -2), ("E", 2)]
    summary = diff["summary"]
    assert summary["with_difference"] == 3 and summary["rows"] == 4
    assert summary["erp_only"] == 1 and summary["wms_only"] == 1
    assert summary["unmapped_warehouses"] == ["BODEGA SIN CÓDIGO"]
    assert summary["snapshot_at"] is not None
    b_row = diff["items"][0]
    assert b_row["erp_lots"][0]["lot_number"] == "L-1" and b_row["name"] == "Bisturí"
    d_row = diff["items"][1]
    assert d_row["in_erp"] is True and d_row["in_wms_catalog"] is False and d_row["wms_stock"] == 0

    assert summary["unknown_storage_codes"] == []

    everything = await erp_stock_service.compare(tenant_id, only_diff=False)
    assert everything["total"] == 4  # A (sin diferencia) también aparece
    search = await erp_stock_service.compare(tenant_id, only_diff=False, q="alco")
    assert [r["sku"] for r in search["items"]] == ["A"] and search["items"][0]["difference"] == 0
