"""Tests for the public (token-gated) bulto consultation used by the QR page."""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.routes.public import get_bulto_public
from app.core.database import get_database
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import order_service, packing_service, picking_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio


async def _admin():
    db = get_database()
    return make_user(await db[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _drive_to_packed_package():
    """Seed → picking → packing con un bulto que tiene items. Devuelve (order, token, pid)."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = await _admin()
    db = get_database()
    order = await db[Collections.ORDERS].find_one({"erp_order_number": "1001"})
    order_id = str(order["_id"])

    plan = []
    for line in order["lines"]:
        bc = await db[Collections.BARCODES].find_one(
            {"tenant_id": tenant_id, "product_id": line["product_id"]}
        )
        plan.append((bc["barcode"], line["ordered_quantity"]))

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    for bc, q in plan:
        await picking_service.scan(tenant_id, task["id"], admin, bc, q, None)
    await picking_service.complete(tenant_id, task["id"], admin)

    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    pid = pk["id"]
    await packing_service.start_task(tenant_id, pid, admin)
    pkg = await packing_service.create_package(tenant_id, pid, admin, "Bulto 1")
    bc0, q0 = plan[0]
    await packing_service.scan(tenant_id, pid, admin, bc0, q0, pkg["package_id"])

    task = await packing_service.get_task(tenant_id, pid)  # backfills/returns tokens
    return order, task["packages"][0]["public_token"], pid


async def test_public_bulto_view():
    order, token, _pid = await _drive_to_packed_package()
    assert token

    view = await get_bulto_public(token)
    assert view.order_number == "1001"
    assert view.customer == order.get("customer")
    assert view.package_number == 1
    assert view.package_count == 1
    assert view.item_count >= 1
    assert view.total_units > 0
    assert all(it.name for it in view.items)  # names resolved from task lines


async def test_public_bulto_not_found():
    with pytest.raises(HTTPException) as exc:
        await get_bulto_public("token-inexistente")
    assert exc.value.status_code == 404


async def test_public_bulto_expired():
    _order, token, pid = await _drive_to_packed_package()
    db = get_database()
    task = await db[Collections.PACKING_TASKS].find_one({"_id": to_object_id(pid)})
    task["packages"][0]["public_expires_at"] = now_utc() - timedelta(days=1)
    await db[Collections.PACKING_TASKS].update_one(
        {"_id": task["_id"]}, {"$set": {"packages": task["packages"]}}
    )
    with pytest.raises(HTTPException) as exc:
        await get_bulto_public(token)
    assert exc.value.status_code == 410
