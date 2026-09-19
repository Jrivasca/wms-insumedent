"""Pedidos importados de Defontana que cambian de estado allá (anulado, cerrado, guía
emitida fuera del WMS…): se cancelan solos si nadie los ha preparado, se marcan para
revisión si ya están en preparación, y se reconsultan con Order/Get si quedaron fuera de
la ventana. Sin red: se reemplaza ``_request``."""
import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import order_sync
from app.integrations.defontana.client import DefontanaConnector
from app.integrations.defontana.mapper import DefontanaMapper
from app.models import Collections

pytestmark = pytest.mark.asyncio


def _fake_api(monkeypatch, headers, orders=None):
    calls = []

    async def fake_request(self, method, path, *, params=None, json=None):
        calls.append((method, path, dict(params or {})))
        if path == "/Order/List":
            return {"success": True, "items": headers}
        if path == "/Order/Get":
            return {"success": True, "orderData": (orders or {})[int(params["number"])]}
        raise AssertionError(path)

    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(DefontanaConnector, "_request", fake_request)
    return calls


async def _setup():
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    tenant_id = str(r.inserted_id)
    u = await tenant_db(tenant_id)[Collections.USERS].insert_one(
        {"role": "supervisor", "is_active": True, "email": "sup@x.cl"}
    )
    return tenant_id, str(u.inserted_id)


async def _order(tenant_id, number, status, erp_status="EEX (EN_DESPACHO_EN_FACTURACION)", **extra):
    r = await tenant_db(tenant_id)[Collections.ORDERS].insert_one(
        {"erp_order_number": str(number), "status": status, "erp_status": erp_status,
         "fulfillment": "complete", "lines": [], **extra}
    )
    return str(r.inserted_id)


async def _get(tenant_id, order_id):
    from bson import ObjectId
    return await tenant_db(tenant_id)[Collections.ORDERS].find_one({"_id": ObjectId(order_id)})


async def _alerts(tenant_id, user_id):
    return await tenant_db(tenant_id)[Collections.NOTIFICATIONS].count_documents(
        {"user_id": user_id, "type": "erp_order_changed"}
    )


async def _sync(tenant_id):
    return await order_sync.sync_orders(tenant_id, "2026-09-01", "2026-09-16")


# ---------------------------------------------------------------------------
async def test_annulled_order_not_yet_prepared_is_cancelled_with_its_picking_task(monkeypatch):
    tenant_id, sup = await _setup()
    order_id = await _order(tenant_id, 7001, "pending_picking")
    db = tenant_db(tenant_id)
    await db[Collections.PICKING_TASKS].insert_one({"order_id": order_id, "status": "pending", "lines": []})
    _fake_api(monkeypatch, [{"number": 7001, "status": "N"}])

    summary = await _sync(tenant_id)

    order = await _get(tenant_id, order_id)
    assert summary["cancelled"] == 1
    assert order["status"] == "cancelled" and order["erp_status"] == "N"
    assert "anulado" in order["cancel_reason"]
    task = await db[Collections.PICKING_TASKS].find_one({"order_id": order_id})
    assert task["status"] == "cancelled"
    assert await _alerts(tenant_id, sup) == 1
    assert await db[Collections.AUDIT_LOGS].find_one({"action": "erp_order_cancelled", "entity_id": order_id})


async def test_closed_order_in_preparation_is_flagged_once_not_cancelled(monkeypatch):
    tenant_id, sup = await _setup()
    order_id = await _order(tenant_id, 7002, "picked")
    _fake_api(monkeypatch, [{"number": 7002, "status": "M"}])

    first = await _sync(tenant_id)
    second = await _sync(tenant_id)

    order = await _get(tenant_id, order_id)
    assert order["status"] == "picked"  # la operación no se toca
    assert "cerrado manualmente" in order["erp_attention"]["reason"]
    assert first["flagged"] == 1 and second["flagged"] == 0
    assert await _alerts(tenant_id, sup) == 1  # un solo aviso por cambio de estado


async def test_open_order_outside_window_is_refreshed_with_order_get(monkeypatch):
    tenant_id, sup = await _setup()
    order_id = await _order(tenant_id, 7003, "imported")
    calls = _fake_api(monkeypatch, [], {7003: {"number": 7003, "status": "DFX (DESPACHADO_FACTURADO)"}})

    summary = await _sync(tenant_id)

    assert ("GET", "/Order/Get", {"number": "7003"}) in calls
    order = await _get(tenant_id, order_id)
    assert summary["cancelled"] == 1 and order["status"] == "cancelled"
    assert "Guía de despacho ya emitida" in order["cancel_reason"]


async def test_still_pending_updates_status_and_clears_attention(monkeypatch):
    tenant_id, sup = await _setup()
    order_id = await _order(tenant_id, 7004, "packing",
                            erp_attention={"reason": "Pedido volvió a aprobación en Defontana (AF)"})
    _fake_api(monkeypatch, [{"number": 7004, "status": "EFX (EN_DESPACHO_FACTURADO)"}],
              {7004: {"number": 7004, "status": "EFX (EN_DESPACHO_FACTURADO)", "details": [], "client": {}}})

    await _sync(tenant_id)

    order = await _get(tenant_id, order_id)
    assert order["status"] == "packing"
    assert order["erp_status"].startswith("EFX") and order["erp_attention"] is None
    assert await _alerts(tenant_id, sup) == 0


async def test_dispatched_and_non_defontana_orders_are_left_alone(monkeypatch):
    tenant_id, sup = await _setup()
    dispatched = await _order(tenant_id, 7005, "dispatched")
    pdf_order = await _order(tenant_id, 7006, "imported", erp_status=None)
    _fake_api(monkeypatch, [{"number": 7005, "status": "DFX (DESPACHADO_FACTURADO)"},
                            {"number": 7006, "status": "N"}])

    summary = await _sync(tenant_id)

    assert summary["cancelled"] == 0 and summary["flagged"] == 0
    assert (await _get(tenant_id, dispatched))["status"] == "dispatched"
    assert (await _get(tenant_id, pdf_order))["status"] == "imported"  # sin erp_status: no es de la API
    assert await _alerts(tenant_id, sup) == 0


@pytest.mark.parametrize(
    "status,reason_part",
    [
        ("EEX (EN_DESPACHO_EN_FACTURACION)", None),
        ("", None),
        ("N", "anulado"),
        ("M", "cerrado manualmente"),
        ("RF", "rechazado financieramente"),
        ("DEX (DESPACHADO_EN_FACTURACION)", "Guía de despacho ya emitida"),
        ("XFS", "sin despacho pendiente"),
        ("AF", "volvió a aprobación"),
    ],
)
async def test_no_longer_pending_reason(status, reason_part):
    reason = DefontanaMapper.order_no_longer_pending_reason(status)
    if reason_part is None:
        assert reason is None
    else:
        assert reason_part in reason
