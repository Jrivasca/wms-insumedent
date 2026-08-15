"""In-app notifications (Phase 1) — fan-out, tenant/user isolation, read flow,
and the edge-triggered stock-zero alert with dedupe."""
from types import SimpleNamespace

import pytest
from bson import ObjectId

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.models.notification import NotificationType
from app.services import dispatch_service, inventory_service, notification_service, order_service
from .conftest import make_user

pytestmark = pytest.mark.asyncio


async def _tenant(name: str) -> str:
    db = get_database()
    r = await db[Collections.TENANTS].insert_one({"name": name, "is_active": True})
    return str(r.inserted_id)


async def _user(tenant_id: str, role: str) -> str:
    db = get_database()
    r = await db[Collections.USERS].insert_one(
        {"tenant_id": tenant_id, "role": role, "is_active": True,
         "name": role, "email": f"{role}-{ObjectId()}@x.cl"}
    )
    return str(r.inserted_id)


async def _warehouse(tenant_id: str, name: str = "WH") -> str:
    db = get_database()
    r = await db[Collections.WAREHOUSES].insert_one(
        {"tenant_id": tenant_id, "name": name, "erp_storage_code": "01", "is_active": True}
    )
    return str(r.inserted_id)


# ---------------------------------------------------------------------------
# emit / fan-out
# ---------------------------------------------------------------------------
async def test_emit_fans_out_to_audience_only():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    picker = await _user(a, "picker")
    sales = await _user(a, "sales")

    n = await notification_service.emit(
        tenant_id=a,
        notification_type=NotificationType.ORDER_CREATED.value,
        title="Nuevo pedido 1",
        body="x",
    )
    # order_created audience = {admin, supervisor, picker}; sales is NOT included.
    assert n == 2
    assert await notification_service.unread_count(a, admin) == 1
    assert await notification_service.unread_count(a, picker) == 1
    assert await notification_service.unread_count(a, sales) == 0


async def test_emit_excludes_actor():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    picker = await _user(a, "picker")

    await notification_service.emit(
        tenant_id=a,
        notification_type=NotificationType.ORDER_CREATED.value,
        title="t", body="b",
        actor_id=admin,
    )
    assert await notification_service.unread_count(a, admin) == 0  # actor skipped
    assert await notification_service.unread_count(a, picker) == 1


async def test_notifications_are_tenant_isolated():
    a = await _tenant("A")
    b = await _tenant("B")
    admin_a = await _user(a, "admin")
    admin_b = await _user(b, "admin")

    await notification_service.emit(
        tenant_id=a, notification_type=NotificationType.STOCK_ZERO.value,
        title="t", body="b",
    )
    assert await notification_service.unread_count(a, admin_a) == 1
    assert await notification_service.unread_count(b, admin_b) == 0  # other tenant unaffected


# ---------------------------------------------------------------------------
# read flow
# ---------------------------------------------------------------------------
async def test_list_mark_read_and_mark_all():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    await _user(a, "supervisor")

    await notification_service.emit(tenant_id=a, notification_type=NotificationType.STOCK_ZERO.value, title="1", body="b")
    await notification_service.emit(tenant_id=a, notification_type=NotificationType.STOCK_ZERO.value, title="2", body="b")

    feed = await notification_service.list_for_user(a, admin)
    assert feed["total"] == 2 and len(feed["items"]) == 2
    assert await notification_service.unread_count(a, admin) == 2

    first_id = feed["items"][0]["id"]
    assert await notification_service.mark_read(a, admin, first_id) == 1
    assert await notification_service.unread_count(a, admin) == 1

    assert await notification_service.mark_all_read(a, admin) == 1
    assert await notification_service.unread_count(a, admin) == 0


async def test_cannot_mark_another_users_notification():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    supervisor = await _user(a, "supervisor")

    await notification_service.emit(tenant_id=a, notification_type=NotificationType.STOCK_ZERO.value, title="1", body="b")
    feed = await notification_service.list_for_user(a, admin)
    admin_notif_id = feed["items"][0]["id"]

    # supervisor tries to mark admin's row: no match, nothing changes.
    assert await notification_service.mark_read(a, supervisor, admin_notif_id) == 0
    assert await notification_service.unread_count(a, admin) == 1


# ---------------------------------------------------------------------------
# integration with business events
# ---------------------------------------------------------------------------
async def test_order_created_emits_notification():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    line = SimpleNamespace(sku="X", name="Prod X", unit="UN", ordered_quantity=2, product_id=None)
    await order_service.create_order_from_lines(
        tenant_id=a, erp_order_number="9001", customer="Cliente", lines=[line], created_by="seed"
    )
    assert await notification_service.unread_count(a, admin) == 1
    feed = await notification_service.list_for_user(a, admin)
    assert feed["items"][0]["type"] == NotificationType.ORDER_CREATED.value


async def test_dispatch_emits_notification():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    sales = await _user(a, "sales")
    db = tenant_db(a)
    order = await db[Collections.ORDERS].insert_one(
        {"erp_order_number": "5005", "customer": "ACME", "status": "ready_to_dispatch",
         "lines": [{"line_id": "L1", "product_id": None, "sku": "X", "name": "X",
                    "ordered_quantity": 2, "picked_quantity": 2, "packed_quantity": 2,
                    "dispatched_quantity": 0, "status": "packed"}]}
    )
    actor = make_user({"_id": ObjectId(), "tenant_id": a, "role": "dispatcher"})
    await dispatch_service.confirm_dispatch(a, str(order.inserted_id), actor, carrier="Correos")

    # dispatched audience = {admin, supervisor, sales}
    assert await notification_service.unread_count(a, admin) == 1
    assert await notification_service.unread_count(a, sales) == 1


# ---------------------------------------------------------------------------
# stock-zero: alert, dedupe, re-arm
# ---------------------------------------------------------------------------
async def test_stock_zero_alert_dedupe_and_rearm():
    a = await _tenant("A")
    admin = await _user(a, "admin")
    wh = await _warehouse(a)
    db = get_database()
    product = await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": a, "sku": "SKU1", "name": "Producto 1"}
    )
    pid = str(product.inserted_id)
    loc = "loc-1"

    # Seed 4 units, then adjust down to 0 -> one stock-zero alert.
    await inventory_service.create_reception(
        tenant_id=a, product_id=pid, warehouse_id=wh, location_id=loc,
        quantity=4, created_by=admin, sync_erp=False,
    )
    await inventory_service.create_adjustment(
        tenant_id=a, product_id=pid, warehouse_id=wh, location_id=loc,
        quantity=-4, reason="merma", created_by=admin,
    )
    assert await notification_service.unread_count(a, admin) == 1

    # A second crossing while still depleted must NOT duplicate (marker dedupe).
    await inventory_service._alert_stock_zero_if_depleted(a, pid, wh)
    assert await notification_service.unread_count(a, admin) == 1

    # Stock returns (clears the marker), then depletes again -> a fresh alert.
    await inventory_service.create_reception(
        tenant_id=a, product_id=pid, warehouse_id=wh, location_id=loc,
        quantity=5, created_by=admin, sync_erp=False,
    )
    await inventory_service.create_adjustment(
        tenant_id=a, product_id=pid, warehouse_id=wh, location_id=loc,
        quantity=-5, reason="merma", created_by=admin,
    )
    assert await notification_service.unread_count(a, admin) == 2
