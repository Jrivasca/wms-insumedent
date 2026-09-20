"""Conciliación WMS ← Defontana, aplicada (decisiones A.3, A.4 y A.5): escribe los ajustes en
el WMS con movimientos de conciliación, deja las diferencias grandes para revisión humana y
NUNCA envía nada al ERP, que ya tiene esas cantidades."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.services import erp_reconcile_service
from app.workers import defontana_scheduler

pytestmark = pytest.mark.asyncio


async def _setup():
    r = await get_database()[Collections.TENANTS].insert_one({"name": "T", "is_active": True})
    tenant_id = str(r.inserted_id)
    db = tenant_db(tenant_id)
    warehouse = str((await db[Collections.WAREHOUSES].insert_one(
        {"name": "BODEGA CENTRAL", "erp_storage_code": "BODEGACENTRAL"})).inserted_id)
    locations = {}
    for code, loc_type in (("SIN-UBICAR", "receiving"), ("A-01", "storage")):
        locations[code] = str((await db[Collections.LOCATIONS].insert_one(
            {"warehouse_id": warehouse, "code": code, "type": loc_type})).inserted_id)
    return tenant_id, db, warehouse, locations


async def _product(db, sku):
    return str((await db[Collections.PRODUCTS].insert_one(
        {"sku": sku, "name": f"Producto {sku}"})).inserted_id)


async def _balance(db, tenant_id, product_id, warehouse_id, location_id, qty):
    await db[Collections.INVENTORY_BALANCES].insert_one({
        "tenant_id": tenant_id, "product_id": product_id, "warehouse_id": warehouse_id,
        "location_id": location_id, "lot_number": None, "serial_number": None,
        "quantity_on_hand": qty, "quantity_reserved": 0, "quantity_blocked": 0,
        "expiration_date": None,
    })


async def _erp(db, sku, qty, synced_at=None):
    await db[Collections.ERP_STOCK].insert_one({
        "sku": sku, "storage_code": "BODEGACENTRAL", "erp_stock": qty,
        "synced_at": synced_at or datetime.now(timezone.utc),
    })


async def _on_hand(db, product_id, location_id):
    total = 0
    async for balance in db[Collections.INVENTORY_BALANCES].find(
            {"product_id": product_id, "location_id": location_id}):
        total += balance.get("quantity_on_hand") or 0
    return total


# ---------------------------------------------------------------------------
async def test_apply_adjusts_the_wms_and_never_sends_anything_to_defontana(monkeypatch):
    # Las dos llaves del envío al ERP ENCENDIDAS: si la conciliación usara el camino de los
    # ajustes normales, aquí encolaría documentos. Con el envío apagado no probaría nada.
    monkeypatch.setattr(settings, "erp_sync_enabled", True)
    monkeypatch.setattr(settings, "defontana_inventory_sync_enabled", True)
    tenant_id, db, warehouse, loc = await _setup()
    falta = await _product(db, "FALTA")  # ERP 10, WMS 4: +6
    sobra = await _product(db, "SOBRA")  # ERP 2, WMS 5: -3
    await _balance(db, tenant_id, falta, warehouse, loc["A-01"], 4)
    await _balance(db, tenant_id, sobra, warehouse, loc["A-01"], 5)
    await _erp(db, "FALTA", 10)
    await _erp(db, "SOBRA", 2)

    result = await erp_reconcile_service.apply(tenant_id, "u-supervisor")

    assert result["applied"] == 2 and result["errors"] == []
    assert await _on_hand(db, falta, loc["SIN-UBICAR"]) == 6  # lo que falta queda sin ubicar
    assert await _on_hand(db, falta, loc["A-01"]) == 4  # lo que ya estaba no se toca
    assert await _on_hand(db, sobra, loc["A-01"]) == 2
    movements = await db[Collections.INVENTORY_MOVEMENTS].find({}).to_list(length=10)
    assert movements and {m["movement_type"] for m in movements} == {"reconciliation"}
    assert all(m["reference_type"] == "reconciliation" for m in movements)
    assert all(m["created_by"] == "u-supervisor" for m in movements)
    assert all(m["reason"].startswith("Conciliación con Defontana") for m in movements)
    assert await db[Collections.SYNC_JOBS].count_documents({}) == 0


async def test_large_differences_wait_for_a_supervisor(monkeypatch):
    monkeypatch.setattr(settings, "defontana_reconcile_review_units", 20)
    tenant_id, db, warehouse, loc = await _setup()
    chica = await _product(db, "CHICA")  # diferencia 5: se aplica sola
    grande = await _product(db, "GRANDE")  # diferencia 100: espera revisión
    await _erp(db, "CHICA", 5)
    await _erp(db, "GRANDE", 100)

    preview = await erp_reconcile_service.preview(tenant_id)
    assert {r["sku"]: r["needs_review"] for r in preview["items"]} == {"CHICA": False, "GRANDE": True}
    assert preview["summary"]["auto"] == 1 and preview["summary"]["to_review"] == 1

    automatica = await erp_reconcile_service.apply(tenant_id, "defontana-auto-sync")
    assert automatica["applied"] == 1 and automatica["skipped_review"] == 1
    assert automatica["pending_review"] == 1
    assert await _on_hand(db, chica, loc["SIN-UBICAR"]) == 5
    assert await _on_hand(db, grande, loc["SIN-UBICAR"]) == 0

    # Un supervisor la aprueba, fila por fila.
    aprobada = await erp_reconcile_service.apply(
        tenant_id, "u-supervisor", keys=[("GRANDE", "BODEGACENTRAL")], include_review=True)
    assert aprobada["applied"] == 1 and aprobada["pending_review"] == 0
    assert await _on_hand(db, grande, loc["SIN-UBICAR"]) == 100


async def test_blocked_rows_are_never_applied():
    tenant_id, db, warehouse, loc = await _setup()
    await _erp(db, "NO-ESTA-EN-EL-WMS", 5)

    result = await erp_reconcile_service.apply(tenant_id, "u1", include_review=True)

    assert result["applied"] == 0 and result["skipped_blocked"] == 1
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 0


async def test_applying_twice_changes_nothing_the_second_time():
    tenant_id, db, warehouse, loc = await _setup()
    await _product(db, "A")
    await _erp(db, "A", 7)

    assert (await erp_reconcile_service.apply(tenant_id, "u1"))["applied"] == 1
    again = await erp_reconcile_service.apply(tenant_id, "u1")

    assert again["applied"] == 0
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 1


async def test_emptying_products_does_not_flood_stock_zero_alerts():
    """La primera conciliación puede dejar en cero cientos de productos: no debe disparar un
    aviso de "sin stock" por cada uno. Hay un supervisor registrado a propósito: sin
    destinatario, ``emit`` no escribe nada y este test pasaría aunque el aviso se disparara."""
    tenant_id, db, warehouse, loc = await _setup()
    await db[Collections.USERS].insert_one({"role": "supervisor", "is_active": True})
    product = await _product(db, "AGOTADO")
    await _balance(db, tenant_id, product, warehouse, loc["A-01"], 3)
    await _erp(db, "AGOTADO", 0)

    result = await erp_reconcile_service.apply(tenant_id, "u1")

    assert result["applied"] == 1 and await _on_hand(db, product, loc["A-01"]) == 0
    assert await db[Collections.NOTIFICATIONS].count_documents({"type": "stock_zero"}) == 0


async def test_daily_task_refuses_a_stale_snapshot():
    """Con una foto vieja "corregiría" el WMS hacia un stock que ya no es el del ERP."""
    tenant_id, db, warehouse, loc = await _setup()
    await _product(db, "A")
    await _erp(db, "A", 7, synced_at=datetime.now(timezone.utc) - timedelta(hours=30))

    with pytest.raises(RuntimeError, match="foto reciente"):
        await defontana_scheduler._run_reconcile(tenant_id)
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 0

    await db[Collections.ERP_STOCK].update_many(
        {}, {"$set": {"synced_at": datetime.now(timezone.utc)}})
    summary = await defontana_scheduler._run_reconcile(tenant_id)
    assert summary["applied"] == 1 and summary["errors"] == 0


async def test_reconcile_task_is_registered_only_when_enabled(monkeypatch):
    assert "reconcile" not in {t.name for t in defontana_scheduler.tasks()}

    monkeypatch.setattr(settings, "defontana_reconcile_enabled", True)
    task = next(t for t in defontana_scheduler.tasks() if t.name == "reconcile")

    assert task.daily_at == settings.defontana_reconcile_at == "04:30"


async def test_it_never_takes_stock_from_an_order_being_prepared():
    """Defontana descuenta al emitir el documento; el WMS todavía tiene esa mercadería en
    STAGING, en la mano del operario. La conciliación NO se la quita al pedido: descuenta lo
    que está libre y deja el resto explicado, para que un humano lo mire."""
    tenant_id, db, warehouse, loc = await _setup()
    staging = str((await db[Collections.LOCATIONS].insert_one(
        {"warehouse_id": warehouse, "code": "STAGING", "type": "staging"})).inserted_id)
    product = await _product(db, "EN-PREPARACION")
    await _balance(db, tenant_id, product, warehouse, staging, 5)
    await _balance(db, tenant_id, product, warehouse, loc["A-01"], 2)
    await _erp(db, "EN-PREPARACION", 4)  # sobran 3 en el WMS

    preview = await erp_reconcile_service.preview(tenant_id)
    row = preview["items"][0]
    assert [(a["type"], a["quantity"]) for a in row["actions"]] == [("remove", 2)]
    assert "preparación" in row["review_reason"]
    assert row["needs_review"] is True  # aunque la diferencia sea chica

    await erp_reconcile_service.apply(tenant_id, "u1", include_review=True)

    assert await _on_hand(db, product, staging) == 5  # el pedido conserva lo suyo
    assert await _on_hand(db, product, loc["A-01"]) == 0


async def test_a_row_only_in_staging_is_blocked_instead_of_applied():
    tenant_id, db, warehouse, loc = await _setup()
    staging = str((await db[Collections.LOCATIONS].insert_one(
        {"warehouse_id": warehouse, "code": "STAGING", "type": "staging"})).inserted_id)
    product = await _product(db, "SOLO-STAGING")
    await _balance(db, tenant_id, product, warehouse, staging, 5)
    await _erp(db, "SOLO-STAGING", 0)

    preview = await erp_reconcile_service.preview(tenant_id)
    assert preview["items"][0]["actions"] == []
    assert "preparación" in preview["items"][0]["blocked"]

    result = await erp_reconcile_service.apply(tenant_id, "u1", include_review=True)

    assert result["applied"] == 0 and await _on_hand(db, product, staging) == 5
