"""Pendiente de un pedido parcial (decisión A.7): se despacha lo que hay y lo que falta sale
después en OTRA guía, desde una tarea de picking nueva con solo lo pendiente.

Lo que no puede pasar nunca: que un retroceso sobre el pendiente toque la guía anterior.
Revertir su packing devolvería a staging mercadería que ya salió (stock fantasma), y poner lo
despachado en cero borraría el registro de esa guía."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import (
    dispatch_service,
    order_service,
    packing_service,
    picking_service,
    replenishment_alert_service,
)
from .conftest import make_user

pytestmark = pytest.mark.asyncio


def _picker(tenant_id: str):
    return make_user({"_id": "picker-1", "tenant_id": tenant_id, "role": "picker"})


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _barcode_for(tenant_id: str, product_id: str) -> str:
    bc = await get_database()[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "product_id": product_id})
    return bc["barcode"]


async def _make_order(tenant_id: str, qtys, number: str):
    """Pedido con cantidades controladas sobre 2 productos del pedido demo 1001 (tienen
    código de barras y stock)."""
    base = await get_database()[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    lines = [
        SimpleNamespace(sku=bl["sku"], name=bl.get("name"), unit=bl.get("unit", "UN"),
                        ordered_quantity=qty, product_id=bl["product_id"])
        for bl, qty in zip(base["lines"], qtys)
    ]
    return await order_service.create_order_from_lines(
        tenant_id=tenant_id, erp_order_number=number, customer="Test",
        lines=lines, created_by="tester")


async def _packing_of(tenant_id: str, picking_task_id: str):
    return await tenant_db(tenant_id)[Collections.PACKING_TASKS].find_one(
        {"picking_task_id": picking_task_id})


async def _pack_all(tenant_id, picking_task_id, user, barcode, qty):
    packing = await _packing_of(tenant_id, picking_task_id)
    packing_id = str(packing["_id"])
    await packing_service.start_task(tenant_id, packing_id, user)
    await packing_service.scan(tenant_id, packing_id, user, barcode, qty, None)
    await packing_service.complete(tenant_id, packing_id, user)
    return packing_id


def _qty(order, field):
    return [line.get(field, 0) or 0 for line in order["lines"]]


async def _first_shipment(tenant_id, number):
    """Pedido [5, 3]: se pickea y empaca solo la línea 0 (la 1 queda corta), y se despacha.
    Queda "despachado" con cumplimiento "parcial": lo que había salió, falta la línea 1."""
    picker, admin = _picker(tenant_id), await _admin()
    order = await _make_order(tenant_id, [5, 3], number)
    order_id = order["id"]
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    bc1 = await _barcode_for(tenant_id, order["lines"][1]["product_id"])
    task = await order_service.create_picking_task(tenant_id, order_id, picker.id)
    await picking_service.scan(tenant_id, task["id"], picker, bc0, 5, None)
    await picking_service.complete(tenant_id, task["id"], picker, allow_partial=True)
    packing_id = await _pack_all(tenant_id, task["id"], picker, bc0, 5)
    dispatch = await dispatch_service.confirm_dispatch(tenant_id, order_id, admin, guide_number="G-1")
    return SimpleNamespace(order_id=order_id, bc1=bc1, task_id=task["id"],
                           packing_id=packing_id, dispatch_id=dispatch["id"],
                           picker=picker, admin=admin,
                           sku1=order["lines"][1]["sku"])


async def _untouched(tenant_id, reference_type, reference_id):
    """Los movimientos de esa referencia existen y ninguno quedó revertido."""
    moves = await tenant_db(tenant_id)[Collections.INVENTORY_MOVEMENTS].find(
        {"reference_type": reference_type, "reference_id": reference_id,
         "is_reversal": {"$ne": True}}).to_list(length=50)
    return bool(moves) and not any(m.get("reversed") for m in moves)


# ---------------------------------------------------------------------------
async def test_the_missing_line_ships_later_in_a_second_guide():
    tenant_id = (await run_seed())["tenant_id"]
    s = await _first_shipment(tenant_id, "9101")

    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "dispatched" and order["fulfillment"] == "partial"
    assert _qty(order, "dispatched_quantity") == [5, 0]

    # Llegó stock (el seed lo tiene): el pedido se ofrece para completar.
    completable = await replenishment_alert_service.evaluate_completable(
        tenant_id, order_id=s.order_id)
    assert completable and completable[0]["lines"][0]["missing"] == 3

    backorder = await picking_service.resume_partial(tenant_id, s.order_id, s.picker)
    assert backorder["is_backorder"] is True and backorder["sequence"] == 2
    # Solo lo que falta: la línea 1, por 3.
    assert [(l["sku"], l["quantity_required"]) for l in backorder["lines"]] == [(s.sku1, 3)]
    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "pending_picking"
    assert _qty(order, "dispatched_quantity") == [5, 0]  # la primera guía no se tocó

    await picking_service.start_task(tenant_id, backorder["id"], s.picker)
    await picking_service.scan(tenant_id, backorder["id"], s.picker, s.bc1, 3, None)
    await picking_service.complete(tenant_id, backorder["id"], s.picker)
    order = await order_service.get_order(tenant_id, s.order_id)
    assert _qty(order, "picked_quantity") == [5, 3]  # suma de las dos tareas
    assert order["fulfillment"] == "complete"

    await _pack_all(tenant_id, backorder["id"], s.picker, s.bc1, 3)
    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "ready_to_dispatch" and _qty(order, "packed_quantity") == [5, 3]

    second = await dispatch_service.confirm_dispatch(
        tenant_id, s.order_id, s.admin, guide_number="G-2")
    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "dispatched" and order["fulfillment"] == "complete"
    assert _qty(order, "dispatched_quantity") == [5, 3]
    # La segunda guía lleva solo el pendiente.
    assert [(l["sku"], l["quantity"]) for l in second["lines"]] == [(s.sku1, 3)]
    # Y la primera sigue intacta, con su inventario ya descontado.
    assert await _untouched(tenant_id, "dispatch", s.dispatch_id)
    assert await _untouched(tenant_id, "packing_task", s.packing_id)


async def test_reopening_the_backorder_picking_leaves_the_first_guide_alone():
    tenant_id = (await run_seed())["tenant_id"]
    s = await _first_shipment(tenant_id, "9102")
    backorder = await picking_service.resume_partial(tenant_id, s.order_id, s.picker)
    await picking_service.start_task(tenant_id, backorder["id"], s.picker)
    await picking_service.scan(tenant_id, backorder["id"], s.picker, s.bc1, 3, None)
    await picking_service.complete(tenant_id, backorder["id"], s.picker)

    reopened = await picking_service.reopen_picking(tenant_id, s.order_id, s.admin)

    assert reopened["id"] == backorder["id"] and reopened["status"] == "in_progress"
    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "picking"
    assert _qty(order, "picked_quantity") == [5, 0]  # solo se descontó el pendiente
    assert _qty(order, "dispatched_quantity") == [5, 0]  # la guía anterior sigue registrada
    assert order["fulfillment"] == "partial"
    first = await tenant_db(tenant_id)[Collections.PICKING_TASKS].find_one(
        {"_id": (await picking_service._load_task(tenant_id, s.task_id))["_id"]})
    assert first["status"] == "completed_with_differences"
    # Lo que ya salió no volvió a staging: sin stock fantasma.
    assert await _untouched(tenant_id, "packing_task", s.packing_id)
    assert await _untouched(tenant_id, "picking_task", s.task_id)
    assert await _untouched(tenant_id, "dispatch", s.dispatch_id)


async def test_reopening_the_backorder_packing_keeps_the_first_guide_packed():
    tenant_id = (await run_seed())["tenant_id"]
    s = await _first_shipment(tenant_id, "9103")
    backorder = await picking_service.resume_partial(tenant_id, s.order_id, s.picker)
    await picking_service.start_task(tenant_id, backorder["id"], s.picker)
    await picking_service.scan(tenant_id, backorder["id"], s.picker, s.bc1, 3, None)
    await picking_service.complete(tenant_id, backorder["id"], s.picker)
    second_packing = await _pack_all(tenant_id, backorder["id"], s.picker, s.bc1, 3)

    reopened = await packing_service.reopen_packing(tenant_id, s.order_id, s.admin)

    assert reopened["id"] == second_packing  # la del pendiente, no la de la guía anterior
    order = await order_service.get_order(tenant_id, s.order_id)
    assert order["status"] == "packing"
    assert _qty(order, "packed_quantity") == [5, 0]
    assert _qty(order, "dispatched_quantity") == [5, 0]
    assert await _untouched(tenant_id, "packing_task", s.packing_id)


async def test_no_backorder_while_packed_goods_are_still_waiting_to_ship():
    """Si queda algo empacado sin despachar, primero se despacha eso: no se abre un pendiente
    en paralelo."""
    tenant_id = (await run_seed())["tenant_id"]
    picker, admin = _picker(tenant_id), await _admin()
    order = await _make_order(tenant_id, [5, 3], "9104")
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    task = await order_service.create_picking_task(tenant_id, order["id"], picker.id)
    await picking_service.scan(tenant_id, task["id"], picker, bc0, 5, None)
    await picking_service.complete(tenant_id, task["id"], picker, allow_partial=True)
    await _pack_all(tenant_id, task["id"], picker, bc0, 5)
    # Se despachan 2 de los 5 empacados: quedan 3 esperando.
    await dispatch_service.confirm_dispatch(
        tenant_id, order["id"], admin, lines=[{"sku": order["lines"][0]["sku"], "quantity": 2}])

    current = await order_service.get_order(tenant_id, order["id"])
    assert current["status"] == "partially_dispatched"
    assert not await replenishment_alert_service.evaluate_completable(
        tenant_id, order_id=order["id"])
    with pytest.raises(HTTPException) as exc:
        await picking_service.resume_partial(tenant_id, order["id"], picker)
    assert exc.value.status_code == 409
