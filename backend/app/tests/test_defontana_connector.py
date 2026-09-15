"""Lecturas del conector Defontana contra respuestas con la forma REAL de la API
(camelCase, sobre con success/…List, paginación obligatoria), tal como respondió
replapi.defontana.com. Sin red: se reemplaza ``_request``."""
import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import client as client_module
from app.integrations.defontana import order_sync, product_sync, warehouse_sync
from app.integrations.defontana.client import (
    DefontanaApiError,
    DefontanaConnector,
    _check_envelope,
)
from app.integrations.defontana.mapper import DefontanaMapper
from app.models import Collections

pytestmark = pytest.mark.asyncio


async def _tenant() -> str:
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    return str(r.inserted_id)


def _fake_api(monkeypatch, handler):
    """Reemplaza la llamada HTTP autenticada; ``handler(method, path, params, json)``."""
    calls = []

    async def fake_request(self, method, path, *, params=None, json=None):
        calls.append((method, path, dict(params or {}), json))
        return handler(method, path, params or {}, json)

    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(DefontanaConnector, "_request", fake_request)
    return calls


def _envelope(list_key, items, total=None, **extra):
    data = {"success": True, "message": "ok", "exceptionMessage": None, list_key: items, **extra}
    if total is not None:
        data["totalItems"] = total
    return data


# ---------------------------------------------------------------------------
async def test_success_false_is_an_error_not_an_empty_list():
    with pytest.raises(DefontanaApiError, match="Credenciales"):
        _check_envelope({"success": False, "message": "Credenciales inválidas"}, "/Sale/GetStorages")
    assert _check_envelope({"success": True, "storageList": []}, "/x") == {"success": True, "storageList": []}


async def test_warehouse_sync_reads_every_page_and_maps_real_fields(monkeypatch):
    monkeypatch.setattr(client_module, "PAGE_SIZE", 2)
    storages = [
        {"code": "BODEGACENTRAL", "description": "BODEGA CENTRAL", "saleAvailable": "S", "active": "S"},
        {"code": "B3215", "description": "BODEGA 3215", "saleAvailable": "N", "active": "N"},
        {"code": "B9", "description": "BODEGA 9", "saleAvailable": "S", "active": "S"},
    ]

    def handler(method, path, params, json):
        page = params["pageNumber"]
        return _envelope("storageList", storages[(page - 1) * 2: page * 2], total=3)

    calls = _fake_api(monkeypatch, handler)
    tenant_id = await _tenant()
    summary = await warehouse_sync.sync_warehouses(tenant_id)

    assert summary == {"synced": 3, "created": 3, "updated": 0}
    assert [c[2]["pageNumber"] for c in calls] == [1, 2]
    assert all(c[2]["itemsPerPage"] == 2 for c in calls)
    b3215 = await tenant_db(tenant_id)[Collections.WAREHOUSES].find_one({"erp_storage_code": "B3215"})
    assert b3215["name"] == "BODEGA 3215"
    assert b3215["is_active"] is False and b3215["sale_available"] is False


async def test_product_sync_maps_active_products_without_clobbering_excel_fields(monkeypatch):
    products = [
        {"active": "S", "code": "0004357", "name": "KIT DE FRESAS MICRODONT ULTRA FINO",
         "detailedDescription": None, "type": "A", "unit": "UN", "stock": 2.0,
         "usesLotes": True, "usesSeries": False},
        {"active": "S", "code": "SERV01", "name": "INSTALACION", "type": "S", "unit": "UN",
         "usesLotes": False, "usesSeries": False},
    ]
    calls = _fake_api(monkeypatch, lambda m, p, params, j: _envelope("productList", products, total=2))
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    await db[Collections.PRODUCTS].insert_one(
        {"sku": "0004357", "name": "viejo", "brand": "MICRODONT", "category": "Fresas"}
    )

    summary = await product_sync.sync_products(tenant_id)

    assert summary["synced"] == 2 and summary["created"] == 1 and summary["updated"] == 1
    assert calls[0][1] == "/Sale/GetSimpleProducts" and calls[0][2]["status"] == 1
    kit = await db[Collections.PRODUCTS].find_one({"sku": "0004357"})
    assert kit["name"] == "KIT DE FRESAS MICRODONT ULTRA FINO"
    assert kit["uses_lots"] is True and kit["is_active"] is True
    assert kit["brand"] == "MICRODONT" and kit["category"] == "Fresas"  # no se pisan
    serv = await db[Collections.PRODUCTS].find_one({"sku": "SERV01"})
    assert serv["is_service"] is True


async def test_order_sync_imports_only_orders_in_dispatch_with_their_lines(monkeypatch):
    headers = [
        {"number": 5001, "creationDate": "2026-09-10T00:00:00", "clientFileId": "1-9",
         "status": "EEX (EN_DESPACHO_EN_FACTURACION)"},
        {"number": 5000, "creationDate": "2026-09-01T00:00:00", "clientFileId": "1-9",
         "status": "DFX (DESPACHADO_FACTURADO)"},
    ]
    order_5001 = {
        "number": 5001, "creationDate": "2026-09-10T00:00:00", "status": "EEX (EN_DESPACHO_EN_FACTURACION)",
        "client": {"name": "Clínica Sonrisa", "fileId": "1-9"},
        "details": [
            {"line": 2, "code": "FLETE", "name": "DESPACHO", "count": 1, "unit": "UN", "isService": True},
            {"line": 1, "code": "0004357", "name": "KIT DE FRESAS", "count": 4.0, "unit": "UN", "isService": False},
        ],
    }

    def handler(method, path, params, json):
        if path == "/Order/List":
            return {"success": True, "items": headers}
        if path == "/Order/Get":
            assert params["number"] == 5001  # nunca se pide el detalle de uno despachado
            return {"success": True, "orderData": order_5001}
        raise AssertionError(path)

    calls = _fake_api(monkeypatch, handler)
    tenant_id = await _tenant()
    summary = await order_sync.sync_orders(tenant_id, "2026-09-01", "2026-09-16")

    assert summary == {"listed": 2, "synced": 1, "skipped_not_pending": 1, "created": 1, "updated": 0,
                       "cancelled": 0, "flagged": 0}
    list_call = calls[0]
    assert list_call[2]["PageNumber"] == 0 and list_call[2]["FromDate"] == "2026-09-01"
    order = await tenant_db(tenant_id)[Collections.ORDERS].find_one({"erp_order_number": "5001"})
    assert order["customer"] == "Clínica Sonrisa"
    assert order["erp_status"].startswith("EEX")
    assert [(l["sku"], l["ordered_quantity"]) for l in order["lines"]] == [("0004357", 4)]
    assert isinstance(order["lines"][0]["ordered_quantity"], int)  # 4.0 de Defontana → 4
    assert not await tenant_db(tenant_id)[Collections.ORDERS].find_one({"erp_order_number": "5000"})


async def test_order_sync_default_window_comes_from_settings(monkeypatch):
    from datetime import date, timedelta

    monkeypatch.setattr(settings, "defontana_orders_window_days", 7)
    calls = _fake_api(monkeypatch, lambda m, p, params, j: {"success": True, "items": []})
    await order_sync.sync_orders(await _tenant())
    assert calls[0][2]["FromDate"] == (date.today() - timedelta(days=7)).isoformat()


async def test_external_document_not_found_is_none_but_other_errors_raise(monkeypatch):
    def handler(method, path, params, json):
        if params["externalDocumentID"] == "WMS-NUEVO":
            return _check_envelope({"success": False, "message": "No existe un documento con el ID externo WMS-NUEVO"}, path)
        return _check_envelope({"success": False, "message": "Token inválido"}, path)

    _fake_api(monkeypatch, handler)
    connector = DefontanaConnector(await _tenant())
    assert await connector.get_inventory_document_by_external_id("WMS-NUEVO") is None
    with pytest.raises(DefontanaApiError):
        await connector.get_inventory_document_by_external_id("WMS-OTRO")


async def test_barcode_lookup_posts_code_list(monkeypatch):
    product = {"code": "0004357", "name": "KIT", "active": "S"}
    calls = _fake_api(monkeypatch, lambda m, p, params, j: _envelope("productList", [product]))
    connector = DefontanaConnector(await _tenant())

    assert await connector.get_product_by_barcode("7801234567890") == product
    method, path, params, body = calls[0]
    assert (method, path) == ("POST", "/Sale/GetProductsPOSByBarCode")
    assert body == {"code": ["7801234567890"]} and params["pageNumber"] == 1


@pytest.mark.parametrize(
    "status,pending",
    [
        ("EEX (EN_DESPACHO_EN_FACTURACION)", True),
        ("EFX (EN_DESPACHO_FACTURADO)", True),
        ("DFX (DESPACHADO_FACTURADO)", False),
        ("DEX (DESPACHADO_EN_FACTURACION)", False),
        ("", False),
        (None, False),
    ],
)
async def test_order_status_pending_dispatch(status, pending):
    assert DefontanaMapper.is_pending_dispatch(status) is pending
