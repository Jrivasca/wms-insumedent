"""Fulfillment parcial (Fase 1): un operario cierra un picking corto por falta de stock,
el pedido queda 'partial', las cantidades del pedido se reconcilian, el faltante queda
visible y los retrocesos resetean la reconciliación."""
from types import SimpleNamespace

import pytest

from app.core.database import get_database
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import (
    dashboard_service,
    order_service,
    packing_service,
    picking_service,
)
from .conftest import make_user

pytestmark = pytest.mark.asyncio


async def _admin_user():
    return await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL})


def _picker(tenant_id: str):
    return make_user({"_id": "picker-1", "tenant_id": tenant_id, "role": "picker"})


async def _barcode_for(tenant_id: str, product_id: str) -> str:
    bc = await get_database()[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "product_id": product_id}
    )
    return bc["barcode"]


async def _make_order(tenant_id: str, qtys, number: str = "9001"):
    """Pedido nuevo con cantidades controladas, reutilizando 2 productos del pedido demo
    1001 (que tienen barcode y stock)."""
    base = await get_database()[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    lines = [
        SimpleNamespace(
            sku=bl["sku"], name=bl.get("name"), unit=bl.get("unit", "UN"),
            ordered_quantity=qty, product_id=bl["product_id"],
        )
        for bl, qty in zip(base["lines"], qtys)
    ]
    return await order_service.create_order_from_lines(
        tenant_id=tenant_id, erp_order_number=number, customer="Test",
        lines=lines, created_by="tester",
    )


async def _short_picked_order(tenant_id, picker):
    """Crea un pedido [5, 3], pickea la línea 0 completa (5) y deja la 1 sin pickear;
    cierra el picking parcial como operario. Devuelve (order_id, bc0, task_id)."""
    order = await _make_order(tenant_id, [5, 3])
    order_id = order["id"]
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    task = await order_service.create_picking_task(tenant_id, order_id, picker.id)
    await picking_service.scan(tenant_id, task["id"], picker, bc0, 5, None)
    return order_id, bc0, task["id"]


# ---------------------------------------------------------------------------
async def test_operator_closes_short_picking_without_supervisor():
    tenant_id = (await run_seed())["tenant_id"]
    picker = _picker(tenant_id)
    order_id, _bc0, task_id = await _short_picked_order(tenant_id, picker)

    # El operario (no supervisor) cierra el picking parcial: antes daba 403, ahora no.
    done = await picking_service.complete(tenant_id, task_id, picker, allow_partial=True)
    assert done["status"] == "completed_with_differences"

    order = await order_service.get_order(tenant_id, order_id)
    assert order["status"] == "picked"          # el pipeline avanza igual
    assert order["fulfillment"] == "partial"     # pero se ve parcial


async def test_short_picking_reconciles_and_missing_line_visible():
    tenant_id = (await run_seed())["tenant_id"]
    picker = _picker(tenant_id)
    order_id, _bc0, task_id = await _short_picked_order(tenant_id, picker)
    await picking_service.complete(tenant_id, task_id, picker, allow_partial=True)

    order = await order_service.get_order(tenant_id, order_id)
    l0, l1 = order["lines"][0], order["lines"][1]
    assert l0["picked_quantity"] == 5 and l0["status"] == "picked"
    assert l1["picked_quantity"] == 0 and l1["status"] == "missing"

    # El faltante NO desaparece del pedido, pero la línea 100% faltante no entra a packing.
    packing = (await packing_service.list_tasks(tenant_id, picker))["items"][0]
    assert len(packing["lines"]) == 1
    assert packing["lines"][0]["line_id"] == l0["line_id"]

    # Y el dashboard lo cuenta como parcial.
    stats = await dashboard_service.get_stats(tenant_id)
    assert stats["orders"]["parciales"] >= 1


async def test_partial_line_quantity_reconciled():
    tenant_id = (await run_seed())["tenant_id"]
    picker = _picker(tenant_id)
    order = await _make_order(tenant_id, [5, 3])
    order_id = order["id"]
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    task = await order_service.create_picking_task(tenant_id, order_id, picker.id)
    await picking_service.scan(tenant_id, task["id"], picker, bc0, 2, None)  # 2 de 5
    await picking_service.complete(tenant_id, task["id"], picker, allow_partial=True)

    order = await order_service.get_order(tenant_id, order_id)
    assert order["lines"][0]["picked_quantity"] == 2
    assert order["lines"][0]["status"] == "partial"
    assert order["fulfillment"] == "partial"


async def test_packing_reconciles_packed_quantity():
    tenant_id = (await run_seed())["tenant_id"]
    picker = _picker(tenant_id)
    order_id, bc0, task_id = await _short_picked_order(tenant_id, picker)
    await picking_service.complete(tenant_id, task_id, picker, allow_partial=True)

    packing = (await packing_service.list_tasks(tenant_id, picker))["items"][0]
    await packing_service.start_task(tenant_id, packing["id"], picker)
    await packing_service.scan(tenant_id, packing["id"], picker, bc0, 5, None)
    await packing_service.complete(tenant_id, packing["id"], picker)  # sin diferencias

    order = await order_service.get_order(tenant_id, order_id)
    assert order["status"] == "ready_to_dispatch"
    assert order["lines"][0]["packed_quantity"] == 5
    assert order["lines"][0]["status"] == "packed"
    assert order["fulfillment"] == "partial"  # sigue parcial (la línea 1 quedó corta)


async def test_reopen_picking_resets_reconciliation():
    tenant_id = (await run_seed())["tenant_id"]
    picker = _picker(tenant_id)
    order_id, _bc0, task_id = await _short_picked_order(tenant_id, picker)
    await picking_service.complete(tenant_id, task_id, picker, allow_partial=True)

    admin = make_user(await _admin_user())  # el retroceso exige supervisor
    await picking_service.reopen_picking(tenant_id, order_id, admin)

    order = await order_service.get_order(tenant_id, order_id)
    for line in order["lines"]:
        assert line["picked_quantity"] == 0
        assert line["packed_quantity"] == 0
        assert line["dispatched_quantity"] == 0
        assert line["status"] == "pending"
    assert order["fulfillment"] == "complete"
