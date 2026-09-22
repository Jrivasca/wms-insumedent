"""Automatizaciones de Defontana: programador de tareas (pedidos cada X minutos en horario
hábil, lotes + stock una vez al día), aviso de envío fallido y payload real de la recepción y
del ajuste hacia Inventory/Insert."""
from datetime import date, datetime, timezone

import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.integrations.defontana import order_sync, product_sync, stock_sync
from app.integrations.defontana.mapper import DefontanaMapper
from app.integrations.defontana.schedule import within_schedule
from app.models import Collections
from app.services import integration_service, inventory_service
from app.workers import defontana_scheduler, sync_worker

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
def _enable_orders(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(settings, "defontana_orders_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_stock_sync_enabled", False)
    monkeypatch.setattr(settings, "defontana_orders_sync_hours", "00:00-23:59")
    monkeypatch.setattr(settings, "defontana_orders_sync_weekdays_only", False)


async def test_scheduler_runs_orders_for_each_active_tenant_and_records_the_result(monkeypatch):
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

    _enable_orders(monkeypatch)
    monkeypatch.setattr(order_sync, "sync_orders", fake_sync)

    assert await defontana_scheduler.run_due() == {"orders": 1}

    assert {t for t, _ in synced} == {ok_tenant, failing_tenant}  # la deshabilitada no corre
    assert all(actor == defontana_scheduler.SCHEDULER_ACTOR for _, actor in synced)
    ok_conn = await tenant_db(ok_tenant)[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"})
    assert ok_conn["last_orders_sync_summary"]["created"] == 1 and ok_conn["last_orders_sync_at"]

    runs = get_database()[Collections.SCHEDULER_RUNS]
    assert (await runs.find_one({"task": "orders", "tenant_id": ok_tenant}))["last_success_at"]
    fallida = await runs.find_one({"task": "orders", "tenant_id": failing_tenant})
    assert "no responde" in fallida["last_error"] and fallida.get("last_success_at") is None
    assert not await runs.find_one({"task": "orders", "tenant_id": disabled_tenant})

    # Enseguida no vuelve a correr: no pasó el intervalo.
    synced.clear()
    assert await defontana_scheduler.run_due() == {}
    assert synced == []


async def test_daily_stock_task_runs_lots_and_stock_once_a_day(monkeypatch):
    tenant_id = await _tenant()
    await _connection(tenant_id)
    calls = []

    async def fake_lots(tid, actor="system"):
        calls.append("lotes")
        return {"synced": 5, "batches": 9}

    async def fake_stock(tid, actor="system"):
        calls.append("stock")
        return {"products": 7, "rows": 7}

    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(settings, "defontana_orders_sync_enabled", False)
    monkeypatch.setattr(settings, "defontana_stock_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_stock_sync_at", "03:30")
    monkeypatch.setattr(product_sync, "sync_products", fake_lots)
    monkeypatch.setattr(stock_sync, "sync_erp_stock", fake_stock)

    antes = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
    despues = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)
    assert await defontana_scheduler.run_due(antes) == {}  # todavía no es la hora
    assert calls == []

    assert await defontana_scheduler.run_due(despues) == {"stock": 1}
    assert calls == ["lotes", "stock"]
    conn = await tenant_db(tenant_id)[Collections.ERP_CONNECTIONS].find_one({"erp": "defontana"})
    assert conn["last_lots_sync_at"]

    calls.clear()
    assert await defontana_scheduler.run_due(despues) == {}  # ya corrió hoy
    assert calls == []


@pytest.mark.parametrize(
    "last_attempt,last_success,expected",
    [
        (None, None, True),                                                  # nunca corrió
        (datetime(2026, 9, 16, 3, 31, tzinfo=timezone.utc), datetime(2026, 9, 16, 3, 31, tzinfo=timezone.utc), False),  # ya corrió hoy
        (datetime(2026, 9, 16, 4, 30, tzinfo=timezone.utc), None, False),     # falló recién: espera
        (datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc), datetime(2026, 9, 15, 3, 31, tzinfo=timezone.utc), True),  # falló hace rato
    ],
)
async def test_daily_task_retries_only_after_a_while(last_attempt, last_success, expected):
    task = defontana_scheduler.Task(name="stock", run=None, daily_at="03:30")
    now = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)
    assert defontana_scheduler.is_due(task, now, last_attempt, last_success) is expected


async def test_a_permanently_failed_sync_job_notifies_supervisors(monkeypatch):
    tenant_id = await _tenant()
    db = get_database()
    supervisor = str((await db[Collections.USERS].insert_one(
        {"tenant_id": tenant_id, "role": "supervisor", "is_active": True, "email": "sup@x.cl"}
    )).inserted_id)

    async def failing_handler(job):
        raise RuntimeError("Defontana rechazó el documento")

    monkeypatch.setitem(sync_worker.HANDLERS, "create_inventory_document", failing_handler)
    job = await db[Collections.SYNC_JOBS].insert_one({
        "tenant_id": tenant_id, "job_type": "create_inventory_document", "payload": {},
        "status": "retrying", "attempts": 4, "max_attempts": 5,
    })

    await sync_worker.process_job(await db[Collections.SYNC_JOBS].find_one({"_id": job.inserted_id}))

    after = await db[Collections.SYNC_JOBS].find_one({"_id": job.inserted_id})
    assert after["status"] == "failed"
    alerta = await tenant_db(tenant_id)[Collections.NOTIFICATIONS].find_one(
        {"user_id": supervisor, "type": "sync_job_failed"}
    )
    assert alerta and "rechazó" in alerta["body"] and alerta["entity_type"] == "sync_job"


async def test_status_reports_auto_sync_state(monkeypatch):
    monkeypatch.setattr(settings, "defontana_mock", False)
    monkeypatch.setattr(settings, "defontana_orders_sync_enabled", True)
    tenant_id = await _tenant()
    await _connection(tenant_id)
    status = await integration_service.get_status(tenant_id)
    auto = status["orders_auto_sync"]
    assert auto["enabled"] is True and auto["interval_minutes"] == settings.defontana_orders_sync_interval_minutes


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
    monkeypatch.setattr(settings, "defontana_inventory_sync_enabled", False)
    assert (await receive())["sync_job_id"] is None  # valores sin confirmar: no se envía

    monkeypatch.setattr(settings, "defontana_inventory_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_reception_document_type", "PE")
    result = await receive(lot="L1")
    job = await db[Collections.SYNC_JOBS].find_one({"job_type": "create_inventory_document"})
    assert result["sync_job_id"] and job
    payload = job["payload"]
    assert payload["documentTypeId"] == "PE"
    assert payload["destinationStowageId"] == "BODEGACENTRAL" and payload["originStowageId"] is None
    assert payload["externalDocumentID"].startswith("WMS-REC-")
    assert payload["gloss"] == "Recepción WMS OC-77"
    assert payload["details"][0]["price"] == 1500 and payload["details"][0]["count"] == 3
    assert payload["details"][0]["lotes"][0]["batchNumber"] == "L1"


async def test_adjustment_also_travels_to_defontana_in_both_directions(monkeypatch):
    """El ajuste cambia la cantidad total: si no viaja al ERP, WMS y Defontana se descuadran."""
    tenant_id = await _tenant()
    db = tenant_db(tenant_id)
    wh = await db[Collections.WAREHOUSES].insert_one({"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})
    prod = await db[Collections.PRODUCTS].insert_one({"sku": "0004357", "name": "KIT DE FRESAS", "cost": 1500})

    async def adjust(quantity, reason):
        await inventory_service.create_adjustment(
            tenant_id=tenant_id, product_id=str(prod.inserted_id), warehouse_id=str(wh.inserted_id),
            location_id="loc-1", quantity=quantity, reason=reason, created_by="u1",
        )

    monkeypatch.setattr(settings, "erp_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_inventory_sync_enabled", False)
    await adjust(2, "conteo")
    assert await db[Collections.SYNC_JOBS].count_documents({}) == 0  # apagado: no se envía

    monkeypatch.setattr(settings, "defontana_inventory_sync_enabled", True)
    await adjust(2, "conteo")
    await adjust(-3, "merma")
    jobs = await db[Collections.SYNC_JOBS].find({"job_type": "create_inventory_document"}).to_list(length=10)
    entrada, salida = (j["payload"] for j in sorted(jobs, key=lambda j: j["payload"]["details"][0]["count"]))

    assert entrada["documentTypeId"] == settings.defontana_adjustment_in_document_type
    assert entrada["destinationStowageId"] == "BODEGACENTRAL" and entrada["originStowageId"] is None
    assert entrada["details"][0]["count"] == 2 and entrada["gloss"] == "Ajuste WMS: conteo"
    assert entrada["externalDocumentID"].startswith("WMS-AJU-")
    assert entrada["reasonId"] == settings.defontana_adjustment_in_reason_id

    assert salida["documentTypeId"] == settings.defontana_adjustment_out_document_type
    assert salida["originStowageId"] == "BODEGACENTRAL" and salida["destinationStowageId"] is None
    assert salida["details"][0]["count"] == 3  # cantidad siempre positiva
    # El motivo depende del sentido. Antes había uno solo que, vacío, caía en el de recepción:
    # una merma viajaba a Defontana como COMPRA.
    assert salida["reasonId"] == settings.defontana_adjustment_out_reason_id
    assert entrada["reasonId"] != salida["reasonId"]


async def test_build_dispatch_order_has_the_verified_structure():
    # B.1: payload de Order/DispatchOrder. Estructura del swagger de pruebas y valores de guías
    # GDVELECT reales (tipo de bien 1, tipo de despacho 1, centro de negocio en el análisis).
    payload = DefontanaMapper.build_dispatch_order(
        order_number=2801, line_count=2, business_center="EMPNEGVTAVTA000",
        assets_type="1", dispatch_type="1", transaction_type="", motive="COMPRA",
        storage_code="BODEGACENTRAL", emission_date=date(2026, 9, 22), gloss="CLINICA X",
    )
    assert payload["orderNumber"] == 2801
    assert payload["dispatchInfo"] == {
        "assetsType": "1", "dispatchType": "1", "transactionType": "", "isTransferDispatch": False,
    }
    assert payload["originStorageInfo"]["code"] == "BODEGACENTRAL"
    assert payload["originStorageInfo"]["motive"] == "COMPRA"
    # El centro de negocio va en el análisis de cliente, bodega de origen y cada línea.
    assert payload["clientAnalysis"]["businessCenter"] == "EMPNEGVTAVTA000"
    assert payload["originStorageInfo"]["storageAnalysis"]["businessCenter"] == "EMPNEGVTAVTA000"
    assert len(payload["orderDetailAnalysis"]) == 2
    assert [d["line"] for d in payload["orderDetailAnalysis"]] == [1, 2]
    assert payload["orderDetailAnalysis"][0]["detailAnalysis"]["businessCenter"] == "EMPNEGVTAVTA000"
    assert payload["emissionDate"] == {"day": 22, "month": 9, "year": 2026}
    assert payload["isTransferDocument"] is False
