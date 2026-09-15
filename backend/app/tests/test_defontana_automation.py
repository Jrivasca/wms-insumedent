"""Automatizaciones de Defontana: horario del sync automático de pedidos, su corrida por
empresa, bloqueo de Sale/* (Ventas no contratado) fuera de pruebas y payload real de la
recepción hacia Inventory/Insert."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import order_sync
from app.integrations.defontana.mapper import DefontanaMapper
from app.integrations.defontana.schedule import within_schedule
from app.models import Collections
from app.services import integration_service, inventory_service
from app.workers import orders_watch

pytestmark = pytest.mark.asyncio


async def _tenant() -> str:
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    return str(r.inserted_id)


async def _connection(tenant_id: str, environment: str = "test", status: str = "connected"):
    await tenant_db(tenant_id)[Collections.ERP_CONNECTIONS].insert_one(
        {"erp": "defontana", "environment": environment, "status": status}
    )


# ---------------------------------------------------------------------------
# Horario
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "when,hours,weekdays_only,expected",
    [
        (datetime(2026, 9, 15, 10, 0), "08:00-19:00", True, True),    # martes
        (datetime(2026, 9, 15, 7, 59), "08:00-19:00", True, False),
        (datetime(2026, 9, 15, 19, 1), "08:00-19:00", True, False),
        (datetime(2026, 9, 19, 10, 0), "08:00-19:00", True, False),   # sábado
        (datetime(2026, 9, 19, 10, 0), "08:00-19:00", False, True),
        (datetime(2026, 9, 15, 3, 0), "mal-escrito", True, True),     # no bloquea
    ],
)
async def test_within_schedule(when, hours, weekdays_only, expected):
    assert within_schedule(when, hours, weekdays_only) is expected


# ---------------------------------------------------------------------------
# Sync automático de pedidos
# ---------------------------------------------------------------------------
async def test_orders_watch_syncs_each_active_tenant_and_records_the_result(monkeypatch):
    ok_tenant, failing_tenant, disabled_tenant = await _tenant(), await _tenant(), await _tenant()
    await _connection(ok_tenant)
    await _connection(failing_tenant, status="error")
    await _connection(disabled_tenant, status="disabled")
    synced = []

    async def fake_sync(tenant_id, from_date=None, to_date=None, actor="system"):
        synced.append((tenant_id, actor))
        if tenant_id == failing_tenant:
            raise RuntimeError("Defontana no responde")
        return {"listed": 3, "synced": 1, "created": 1, "updated": 0, "cancelled": 0, "flagged": 0}

    monkeypatch.setattr(order_sync, "sync_orders", fake_sync)

    assert await orders_watch.run_once() == 1

    assert {t for t, _ in synced} == {ok_tenant, failing_tenant}  # la deshabilitada no corre
    assert all(actor == orders_watch.AUTO_SYNC_ACTOR for _, actor in synced)
    ok_conn = await tenant_db(ok_tenant)[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"})
    assert ok_conn["last_orders_sync_summary"]["created"] == 1
    assert ok_conn["last_orders_sync_error"] is None and ok_conn["last_orders_sync_at"]
    bad_conn = await tenant_db(failing_tenant)[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"})
    assert "no responde" in bad_conn["last_orders_sync_error"]
    off_conn = await tenant_db(disabled_tenant)[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"})
    assert "last_orders_sync_at" not in off_conn


async def test_status_reports_auto_sync_state(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(settings, "defontana_orders_sync_enabled", True)
    tenant_id = await _tenant()
    await _connection(tenant_id)
    status = await integration_service.get_status(tenant_id)
    auto = status["orders_auto_sync"]
    assert auto["enabled"] is True and auto["interval_minutes"] == settings.defontana_orders_sync_interval_minutes


# ---------------------------------------------------------------------------
# Sale/* (Ventas no contratado)
# ---------------------------------------------------------------------------
async def test_sale_api_blocked_in_production_but_allowed_in_test(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(settings, "defontana_sale_api_enabled", False)
    prod, test = await _tenant(), await _tenant()
    await _connection(prod, environment="production")
    await _connection(test, environment="test")

    with pytest.raises(HTTPException) as exc:
        await integration_service.run_sync_products(prod, "admin")
    assert exc.value.status_code == 409 and "Ventas" in exc.value.detail
    with pytest.raises(HTTPException):
        await integration_service.run_sync_warehouses(prod, "admin")

    assert (await integration_service.get_status(prod))["sale_api_available"] is False
    assert (await integration_service.get_status(test))["sale_api_available"] is True

    monkeypatch.setattr(settings, "defontana_sale_api_enabled", True)  # si algún día se contrata
    assert (await integration_service.get_status(prod))["sale_api_available"] is True


# ---------------------------------------------------------------------------
# Recepción → Inventory/Insert
# ---------------------------------------------------------------------------
async def test_inventory_entry_payload_has_the_verified_structure():
    payload = DefontanaMapper.build_inventory_entry(
        external_document_id="WMS-REC-1", document_type="MOV001", reason_id="COMPRA",
        business_center="EMPNEGVTAVTA000", centralizable=False, storage_code="BODEGACENTRAL",
        movement_date=date(2026, 9, 15), gloss="Recepción WMS OC-10",
        lines=[{"code": "MONOJET005", "description": "MONOJET", "count": 8.0, "price": 416.5,
                "lot_number": "L-2026", "expiration_date": datetime(2027, 12, 31)}],
    )
    assert payload["documentTypeId"] == "MOV001" and payload["reasonId"] == "COMPRA"
    assert payload["fiscalYear"] == "2026" and payload["date"] == "2026-09-15T00:00:00"
    assert payload["destinationStowageId"] == "BODEGACENTRAL"
    assert payload["clientId"] is None and payload["providerId"] is None and payload["originStowageId"] is None
    assert payload["analysis"]["businessCenter"] == "EMPNEGVTAVTA000"
    line = payload["details"][0]
    assert line["articleId"] == "MONOJET005" and line["count"] == 8 and isinstance(line["count"], int)
    assert line["analysis"]["businessCenter"] == "EMPNEGVTAVTA000"
    assert line["lotes"] == [{"batchNumber": "L-2026", "amount": 8, "expirationDate": "2027-12-31T00:00:00"}]
    assert payload["total"] == 8 * 416.5 and payload["folio"] == 0


async def test_reception_is_sent_only_with_both_flags_and_uses_configured_values(monkeypatch):
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    wh = await db[Collections.WAREHOUSES].insert_one({"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})
    prod = await db[Collections.PRODUCTS].insert_one({"sku": "0004357", "name": "KIT DE FRESAS", "cost": 1500})

    async def receive(lot=None):
        return await inventory_service.create_reception(
            tenant_id=tenant_id, product_id=str(prod.inserted_id), warehouse_id=str(wh.inserted_id),
            location_id="loc-1", quantity=3, created_by="u1", reference="OC-77", lot_number=lot,
        )

    monkeypatch.setattr(settings, "erp_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_reception_sync_enabled", False)
    assert (await receive())["sync_job_id"] is None  # valores sin confirmar: no se envía

    monkeypatch.setattr(settings, "defontana_reception_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_reception_document_type", "PE")
    result = await receive(lot="L1")
    job = await db[Collections.SYNC_JOBS].find_one({"job_type": "create_inventory_document"})
    assert result["sync_job_id"] and job
    payload = job["payload"]
    assert payload["documentTypeId"] == "PE"
    assert payload["destinationStowageId"] == "BODEGACENTRAL"
    assert payload["externalDocumentID"].startswith("WMS-REC-")
    assert payload["gloss"] == "Recepción WMS OC-77"
    assert payload["details"][0]["price"] == 1500 and payload["details"][0]["count"] == 3
    assert payload["details"][0]["lotes"][0]["batchNumber"] == "L1"
