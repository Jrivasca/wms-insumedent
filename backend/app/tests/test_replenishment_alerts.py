"""Alerta de reposición (levantamiento Req. 1): una recepción que cubre el faltante de un
pedido parcial avisa a bodega una sola vez, respeta stock pickeable y antigüedad, y el
operario retoma el pedido solo ("Completar faltante") hasta dejarlo completo."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.models.notification import NotificationType
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import (
    inventory_service,
    order_service,
    picking_service,
    replenishment_alert_service,
)
from .conftest import make_user

pytestmark = pytest.mark.asyncio


async def _barcode_for(tenant_id: str, product_id: str) -> str:
    bc = await get_database()[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "product_id": product_id}
    )
    return bc["barcode"]


async def _alerts(tenant_id: str, user_id: str) -> int:
    return await tenant_db(tenant_id)[Collections.NOTIFICATIONS].count_documents(
        {"user_id": user_id, "type": NotificationType.RECEIPT_UNBLOCKS_ORDER.value}
    )


async def _location(tenant_id: str, warehouse_id: str, code: str, loc_type: str) -> str:
    r = await tenant_db(tenant_id)[Collections.LOCATIONS].insert_one(
        {"warehouse_id": warehouse_id, "code": code, "name": code, "type": loc_type,
         "is_active": True}
    )
    return str(r.inserted_id)


async def _setup():
    """Seed + operario (picker) + bodega. El admin pickea; el picker recibe los avisos."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))
    r = await tenant_db(tenant_id)[Collections.USERS].insert_one(
        {"role": "picker", "is_active": True, "name": "Niño", "email": "picker@demo.cl"}
    )
    picker = make_user({"_id": r.inserted_id, "tenant_id": tenant_id, "role": "picker"})
    return tenant_id, seed["warehouse_id"], admin, picker


async def _short_order(tenant_id: str, admin, number: str):
    """Pedido [5, 3] con los productos del demo 1001: se pickea la línea 0 completa, la 1
    queda en 0 y se cierra parcial. Devuelve (order_id, product_id de la línea corta)."""
    base = await get_database()[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    lines = [
        SimpleNamespace(sku=bl["sku"], name=bl.get("name"), unit="UN",
                        ordered_quantity=qty, product_id=bl["product_id"])
        for bl, qty in zip(base["lines"], [5, 3])
    ]
    order = await order_service.create_order_from_lines(
        tenant_id=tenant_id, erp_order_number=number, customer="Test",
        lines=lines, created_by="tester",
    )
    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    await picking_service.scan(tenant_id, task["id"], admin, bc0, 5, None)
    await picking_service.complete(tenant_id, task["id"], admin, allow_partial=True)
    return order["id"], order["lines"][1]["product_id"]


async def _drain(tenant_id: str, product_id: str) -> None:
    """Deja sin stock el producto (la razón por la que el pedido quedó parcial)."""
    await tenant_db(tenant_id)[Collections.INVENTORY_BALANCES].update_many(
        {"product_id": product_id},
        {"$set": {"quantity_on_hand": 0, "quantity_available": 0}},
    )


async def _receive(tenant_id, product_id, warehouse_id, location_id, qty, actor):
    await inventory_service.create_reception(
        tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        location_id=location_id, quantity=qty, created_by=actor.id, sync_erp=False,
    )


# ---------------------------------------------------------------------------
async def test_reception_covering_shortfall_alerts_floor_once():
    tenant_id, wh, admin, picker = await _setup()
    order_id, pid = await _short_order(tenant_id, admin, "9001")
    await _drain(tenant_id, pid)
    loc = await _location(tenant_id, wh, "B-01-01", "storage")

    await _receive(tenant_id, pid, wh, loc, 3, admin)
    assert await _alerts(tenant_id, picker.id) == 1
    assert await _alerts(tenant_id, admin.id) == 0  # quien recibe no se avisa a sí mismo

    feed = await tenant_db(tenant_id)[Collections.NOTIFICATIONS].find_one(
        {"user_id": picker.id, "type": NotificationType.RECEIPT_UNBLOCKS_ORDER.value}
    )
    assert feed["metadata"]["order_ids"] == [order_id]
    assert "9001" in feed["body"]

    # Más stock del mismo producto mientras el aviso sigue abierto: no duplica.
    await _receive(tenant_id, pid, wh, loc, 2, admin)
    assert await _alerts(tenant_id, picker.id) == 1

    ready = await replenishment_alert_service.evaluate_completable(tenant_id)
    assert [o["order_id"] for o in ready] == [order_id]
    assert ready[0]["lines"][0]["missing"] == 3


async def test_insufficient_reception_does_not_alert():
    tenant_id, wh, admin, picker = await _setup()
    _order_id, pid = await _short_order(tenant_id, admin, "9001")
    await _drain(tenant_id, pid)
    loc = await _location(tenant_id, wh, "B-01-01", "storage")

    await _receive(tenant_id, pid, wh, loc, 2, admin)  # faltan 3
    assert await _alerts(tenant_id, picker.id) == 0
    assert await replenishment_alert_service.evaluate_completable(tenant_id) == []


async def test_reception_into_quarantine_does_not_alert():
    tenant_id, wh, admin, picker = await _setup()
    _order_id, pid = await _short_order(tenant_id, admin, "9001")
    await _drain(tenant_id, pid)
    quarantine = await tenant_db(tenant_id)[Collections.LOCATIONS].find_one(
        {"warehouse_id": wh, "type": "quarantine"}
    )

    await _receive(tenant_id, pid, wh, str(quarantine["_id"]), 10, admin)
    assert await _alerts(tenant_id, picker.id) == 0


async def test_stock_goes_to_oldest_order_first():
    tenant_id, wh, admin, picker = await _setup()
    older_id, pid = await _short_order(tenant_id, admin, "9001")
    _newer_id, _ = await _short_order(tenant_id, admin, "9002")
    await _drain(tenant_id, pid)
    loc = await _location(tenant_id, wh, "B-01-01", "storage")

    await _receive(tenant_id, pid, wh, loc, 3, admin)  # alcanza para uno solo
    notif = await tenant_db(tenant_id)[Collections.NOTIFICATIONS].find_one(
        {"user_id": picker.id, "type": NotificationType.RECEIPT_UNBLOCKS_ORDER.value}
    )
    assert notif["metadata"]["order_ids"] == [older_id]


async def test_picker_resumes_partial_order_and_completes_it():
    tenant_id, wh, admin, picker = await _setup()
    order_id, pid = await _short_order(tenant_id, admin, "9001")
    await _drain(tenant_id, pid)
    loc = await _location(tenant_id, wh, "B-01-01", "storage")
    await _receive(tenant_id, pid, wh, loc, 3, admin)

    # El operario (no supervisor, no asignado) retoma el pedido solo.
    task = await picking_service.resume_partial(tenant_id, order_id, picker)
    assert task["assigned_to"] == picker.id
    assert task["status"] == "in_progress"
    short = next(l for l in task["lines"] if l["product_id"] == pid)
    assert short["status"] == "pending" and "missing_reason" not in short
    assert short["suggested_location_id"] == loc  # donde entró el stock nuevo
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "picking"

    # El aviso quedó liberado (un nuevo faltante volvería a avisar).
    assert not await tenant_db(tenant_id)[Collections.REPLENISHMENT_ALERTS].find_one(
        {"order_id": order_id, "active": True}
    )

    # Escanea solo lo que faltaba y cierra sin diferencias.
    bc1 = await _barcode_for(tenant_id, pid)
    await picking_service.scan(tenant_id, task["id"], picker, bc1, 3, None)
    done = await picking_service.complete(tenant_id, task["id"], picker)
    assert done["status"] == "completed"

    order = await order_service.get_order(tenant_id, order_id)
    assert order["status"] == "picked"
    assert order["fulfillment"] == "complete"
    # El inventario salió de la ubicación donde estaba el stock nuevo.
    bal = await inventory_service.get_balance_doc(tenant_id, pid, wh, loc)
    assert bal["quantity_on_hand"] == 0


async def test_resume_refused_without_stock():
    tenant_id, _wh, admin, picker = await _setup()
    order_id, pid = await _short_order(tenant_id, admin, "9001")
    await _drain(tenant_id, pid)

    with pytest.raises(HTTPException) as exc:
        await picking_service.resume_partial(tenant_id, order_id, picker)
    assert exc.value.status_code == 409
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "picked"
