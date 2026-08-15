"""Despachos divididos (Fase 2): un pedido se despacha en varias guías; el pedido queda
'partially_dispatched' hasta completar el 100%; cada despacho mueve inventario y se puede
anular una guía puntual revirtiendo solo lo suyo."""
from types import SimpleNamespace

import pytest

from app.api.routes.public import get_bulto_public
from app.core.database import get_database
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import dispatch_service, order_service, packing_service, picking_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _barcode_for(tenant_id, product_id):
    bc = await get_database()[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "product_id": product_id}
    )
    return bc["barcode"]


async def _make_order(tenant_id, qtys, number="9100"):
    base = await get_database()[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    lines = [
        SimpleNamespace(sku=bl["sku"], name=bl.get("name"), unit=bl.get("unit", "UN"),
                        ordered_quantity=qty, product_id=bl["product_id"])
        for bl, qty in zip(base["lines"], qtys)
    ]
    return await order_service.create_order_from_lines(
        tenant_id=tenant_id, erp_order_number=number, customer="Test",
        lines=lines, created_by="tester",
    )


async def _drive_to_ready(tenant_id, user, qtys):
    """Pedido completamente pickeado y empacado (ready_to_dispatch). Devuelve (order_id, skus)."""
    order = await _make_order(tenant_id, qtys)
    oid = order["id"]
    skus = [ln["sku"] for ln in order["lines"]]
    bcs = [await _barcode_for(tenant_id, ln["product_id"]) for ln in order["lines"]]
    task = await order_service.create_picking_task(tenant_id, oid, user.id)
    for bc, q in zip(bcs, qtys):
        await picking_service.scan(tenant_id, task["id"], user, bc, q, None)
    await picking_service.complete(tenant_id, task["id"], user)
    pk = (await packing_service.list_tasks(tenant_id, user))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], user)
    for bc, q in zip(bcs, qtys):
        await packing_service.scan(tenant_id, pk["id"], user, bc, q, None)
    await packing_service.complete(tenant_id, pk["id"], user)
    return oid, skus


# ---------------------------------------------------------------------------
async def test_split_dispatch_two_guides():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])

    d1 = await dispatch_service.confirm_dispatch(
        tenant_id, oid, admin, guide_number="G-A", lines=[{"sku": sku0, "quantity": 5}]
    )
    assert d1["guide_number"] == "G-A" and len(d1["lines"]) == 1
    order = await order_service.get_order(tenant_id, oid)
    assert order["status"] == "partially_dispatched"
    assert order["lines"][0]["dispatched_quantity"] == 5
    assert order["lines"][1]["dispatched_quantity"] == 0

    d2 = await dispatch_service.confirm_dispatch(
        tenant_id, oid, admin, guide_number="G-B", lines=[{"sku": sku1, "quantity": 3}]
    )
    assert d2["guide_number"] == "G-B"
    order = await order_service.get_order(tenant_id, oid)
    assert order["status"] == "dispatched"
    assert order["lines"][1]["dispatched_quantity"] == 3

    guias = await dispatch_service.list_order_dispatches(tenant_id, oid)
    assert guias["total"] == 2


async def test_dispatch_registers_inventory_move():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, _sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])
    await dispatch_service.confirm_dispatch(tenant_id, oid, admin, lines=[{"sku": sku0, "quantity": 5}])

    mv = await get_database()[Collections.INVENTORY_MOVEMENTS].find_one(
        {"tenant_id": tenant_id, "movement_type": "dispatch"}
    )
    assert mv is not None
    assert mv["reference_type"] == "dispatch"


async def test_cancel_one_of_two_dispatches():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])
    d1 = await dispatch_service.confirm_dispatch(tenant_id, oid, admin, guide_number="G-A",
                                                 lines=[{"sku": sku0, "quantity": 5}])
    d2 = await dispatch_service.confirm_dispatch(tenant_id, oid, admin, guide_number="G-B",
                                                 lines=[{"sku": sku1, "quantity": 3}])
    assert (await order_service.get_order(tenant_id, oid))["status"] == "dispatched"

    # Anular solo la guía A: revierte lo suyo, la B queda intacta.
    await dispatch_service.cancel_dispatch_by_id(tenant_id, d1["id"], admin)
    order = await order_service.get_order(tenant_id, oid)
    assert order["lines"][0]["dispatched_quantity"] == 0  # revertido
    assert order["lines"][1]["dispatched_quantity"] == 3  # intacto
    assert order["status"] == "partially_dispatched"

    assert (await dispatch_service.get_dispatch(tenant_id, d1["id"]))["status"] == "cancelled"
    assert (await dispatch_service.get_dispatch(tenant_id, d2["id"]))["status"] != "cancelled"


async def test_over_dispatch_blocked():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, _sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])
    with pytest.raises(Exception):
        await dispatch_service.confirm_dispatch(tenant_id, oid, admin,
                                                lines=[{"sku": sku0, "quantity": 99}])


async def test_redispatch_blocked_when_nothing_remaining():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, _skus = await _drive_to_ready(tenant_id, admin, [5, 3])
    await dispatch_service.confirm_dispatch(tenant_id, oid, admin)  # todo -> dispatched
    with pytest.raises(Exception):
        await dispatch_service.confirm_dispatch(tenant_id, oid, admin)


async def test_public_bulto_resolves_its_guide():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [2], number="9200")
    oid = order["id"]
    sku0 = order["lines"][0]["sku"]
    bc0 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])

    task = await order_service.create_picking_task(tenant_id, oid, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, bc0, 2, None)
    await picking_service.complete(tenant_id, task["id"], admin)
    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    pkg = await packing_service.create_package(tenant_id, pk["id"], admin, "Bulto 1")
    await packing_service.scan(tenant_id, pk["id"], admin, bc0, 2, pkg["package_id"])
    await packing_service.complete(tenant_id, pk["id"], admin)

    # Despachar ese bulto en la guía G-QR.
    await dispatch_service.confirm_dispatch(tenant_id, oid, admin, guide_number="G-QR",
                                            package_ids=[pkg["package_id"]])
    assert (await order_service.get_order(tenant_id, oid))["status"] == "dispatched"

    view = await get_bulto_public(pkg["public_token"])
    assert view.dispatch.dispatched is True
    assert view.dispatch.guide_number == "G-QR"
