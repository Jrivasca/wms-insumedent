"""Lecturas del conector Defontana contra respuestas con la forma REAL de la API
(camelCase, sobre con success/…List, paginación obligatoria), tal como respondió
replapi.defontana.com. Sin red: se reemplaza ``_request``."""
import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import client as client_module
from app.integrations.defontana import order_sync, product_sync
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
        _check_envelope({"success": False, "message": "Credenciales inválidas"}, "/Inventory/GetBatchesInfo")
    assert _check_envelope({"success": True, "productDetail": []}, "/x") == {"success": True, "productDetail": []}


async def test_paged_listing_reads_every_page_starting_at_zero(monkeypatch):
    monkeypatch.setattr(client_module, "PAGE_SIZE", 2)
    products = [
        {"active": "S", "code": f"P{i}", "name": f"Producto {i}", "type": "A", "unit": "UN"}
        for i in range(3)
    ]

    def handler(method, path, params, json):
        page = params["pageNumber"]  # GetBatchesInfo parte en la página 0
        return _envelope("productDetail", products[page * 2: (page + 1) * 2], total=3)

    calls = _fake_api(monkeypatch, handler)
    tenant_id = await _tenant()
    summary = await product_sync.sync_products(tenant_id)

    assert summary["synced"] == 3 and summary["created"] == 3
    assert [c[2]["pageNumber"] for c in calls] == [0, 1]
    assert all(c[1] == "/Inventory/GetBatchesInfo" and c[2]["itemsPerPage"] == 2 for c in calls)
    assert await tenant_db(tenant_id)[Collections.PRODUCTS].count_documents({}) == 3


async def test_product_sync_uses_inventory_catalog_keeps_excel_fields_and_stores_lots(monkeypatch):
    products = [
        {"active": "S", "code": "0004357", "name": "KIT DE FRESAS MICRODONT ULTRA FINO",
         "detailedDescription": None, "type": "A", "unit": "UN", "usesLotes": True, "usesSeries": False,
         "storageDetail": [{"storageID": "BODEGACENTRAL", "stock": 3.0, "batchDetail": [
             {"batchNumber": "L-26", "stock": 3.0, "expirationDate": "2027-06-30T00:00:00",
              "storageID": "BODEGACENTRAL"}]}]},
        {"active": "N", "code": "VIEJO", "name": "DESCONTINUADO", "type": "A", "unit": "UN"},
        {"active": "N", "code": "NUNCA", "name": "INACTIVO SIN CREAR", "type": "A", "unit": "UN"},
    ]
    calls = _fake_api(monkeypatch, lambda m, p, params, j: _envelope("productDetail", products, total=3))
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    await db[Collections.PRODUCTS].insert_one(
        {"sku": "0004357", "name": "viejo", "brand": "MICRODONT", "category": "Fresas"}
    )
    await db[Collections.PRODUCTS].insert_one({"sku": "VIEJO", "name": "DESCONTINUADO", "is_active": True})

    summary = await product_sync.sync_products(tenant_id)

    assert summary == {"synced": 3, "created": 0, "updated": 1, "deactivated": 1, "skipped": 1, "batches": 1}
    assert calls[0][1] == "/Inventory/GetBatchesInfo"
    kit = await db[Collections.PRODUCTS].find_one({"sku": "0004357"})
    assert kit["name"] == "KIT DE FRESAS MICRODONT ULTRA FINO"
    assert kit["uses_lots"] is True and kit["is_active"] is True
    assert kit["brand"] == "MICRODONT" and kit["category"] == "Fresas"  # no se pisan
    assert (await db[Collections.PRODUCTS].find_one({"sku": "VIEJO"}))["is_active"] is False
    assert not await db[Collections.PRODUCTS].find_one({"sku": "NUNCA"})  # inactivo: no se crea
    lot = await db[Collections.ERP_BATCHES].find_one({"sku": "0004357"})
    assert lot["lot_number"] == "L-26" and lot["storage_code"] == "BODEGACENTRAL" and lot["stock"] == 3.0
    assert lot["expiration_date"].year == 2027


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
