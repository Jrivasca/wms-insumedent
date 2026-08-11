"""Cross-tenant isolation tests (backlog section 0).

Two guarantees are covered:

1. The ``tenant_db`` data-access layer scopes every read/write to one tenant, so
   a query that forgets ``tenant_id`` cannot leak another company's data and an
   explicit cross-tenant filter/document is rejected loudly.
2. ``allowed_warehouse_ids`` actually restricts what a warehouse-scoped operator
   can see and operate (it used to be persisted but never enforced).

Plus a regression guard: request-scoped services must not reach the raw,
un-scoped ``get_database()``.
"""
from pathlib import Path

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import CrossTenantAccessError, tenant_db, TenantDatabase
from app.models import Collections
from app.services import (
    inventory_service,
    order_service,
    picking_service,
    product_service,
    warehouse_service,
)
from .conftest import make_user

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
async def _make_tenant(name: str) -> str:
    db = get_database()
    result = await db[Collections.TENANTS].insert_one({"name": name, "is_active": True})
    return str(result.inserted_id)


async def _make_warehouse(tenant_id: str, name: str) -> str:
    """Insert a warehouse directly (raw) so the tenant_db paths under test are the
    only thing being exercised by the assertions."""
    db = get_database()
    result = await db[Collections.WAREHOUSES].insert_one(
        {"tenant_id": tenant_id, "name": name, "erp_storage_code": "01", "is_active": True}
    )
    return str(result.inserted_id)


def _admin(tenant_id: str) -> "object":
    return make_user({"_id": ObjectId(), "tenant_id": tenant_id, "role": "admin"})


def _operator(tenant_id: str, allowed):
    return make_user(
        {
            "_id": ObjectId(),
            "tenant_id": tenant_id,
            "role": "picker",
            "allowed_warehouse_ids": list(allowed),
        }
    )


async def _seed_balance(tenant_id, product_id, warehouse_id, location_id, qty):
    db = tenant_db(tenant_id)
    await db[Collections.INVENTORY_BALANCES].insert_one(
        {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "location_id": location_id,
            "lot_number": None,
            "serial_number": None,
            "quantity_on_hand": qty,
            "quantity_reserved": 0,
            "quantity_blocked": 0,
            "quantity_available": qty,
        }
    )


# ---------------------------------------------------------------------------
# 1. Raw wrapper behaviour
# ---------------------------------------------------------------------------
async def test_wrapper_requires_tenant():
    with pytest.raises(ValueError):
        TenantDatabase(get_database(), "")


async def test_wrapper_injects_tenant_on_insert_and_isolates_reads():
    a = await _make_tenant("A")
    b = await _make_tenant("B")

    # Insert WITHOUT tenant_id; the wrapper must stamp it.
    res = await tenant_db(a)[Collections.PRODUCTS].insert_one({"sku": "X", "name": "X"})
    pid = res.inserted_id
    raw = await get_database()[Collections.PRODUCTS].find_one({"_id": pid})
    assert raw["tenant_id"] == a

    # Tenant A sees it; tenant B does not — even by direct _id.
    assert await tenant_db(a)[Collections.PRODUCTS].find_one({"sku": "X"}) is not None
    assert await tenant_db(b)[Collections.PRODUCTS].find_one({"sku": "X"}) is None
    assert await tenant_db(b)[Collections.PRODUCTS].find_one({"_id": pid}) is None


async def test_wrapper_rejects_cross_tenant_filter():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    with pytest.raises(CrossTenantAccessError):
        await tenant_db(a)[Collections.PRODUCTS].find_one({"tenant_id": b})


async def test_wrapper_rejects_cross_tenant_document():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    with pytest.raises(CrossTenantAccessError):
        await tenant_db(a)[Collections.PRODUCTS].insert_one({"tenant_id": b, "sku": "X"})


async def test_wrapper_rejects_cross_tenant_update():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    await tenant_db(a)[Collections.PRODUCTS].insert_one({"sku": "X"})
    with pytest.raises(CrossTenantAccessError):
        await tenant_db(a)[Collections.PRODUCTS].update_one(
            {"sku": "X"}, {"$set": {"tenant_id": b}}
        )


async def test_wrapper_find_only_returns_own_tenant():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    await tenant_db(a)[Collections.PRODUCTS].insert_one({"sku": "A1"})
    await tenant_db(a)[Collections.PRODUCTS].insert_one({"sku": "A2"})
    await tenant_db(b)[Collections.PRODUCTS].insert_one({"sku": "B1"})

    a_docs = await tenant_db(a)[Collections.PRODUCTS].find({}).to_list(length=100)
    assert {d["sku"] for d in a_docs} == {"A1", "A2"}
    assert await tenant_db(a)[Collections.PRODUCTS].count_documents({}) == 2
    assert await tenant_db(b)[Collections.PRODUCTS].count_documents({}) == 1


# ---------------------------------------------------------------------------
# 2. Service-level isolation
# ---------------------------------------------------------------------------
async def test_products_service_isolation():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    pa = await product_service.create_product(a, {"sku": "SKU-A", "name": "A", "barcode": "111"}, "seed", sync_erp=False)
    pb = await product_service.create_product(b, {"sku": "SKU-B", "name": "B", "barcode": "222"}, "seed", sync_erp=False)

    list_a = await product_service.list_products(a)
    assert {p["sku"] for p in list_a["items"]} == {"SKU-A"}

    # B's product is invisible to A, both by id and by barcode.
    with pytest.raises(HTTPException):
        await product_service.get_product(a, pb["id"])
    with pytest.raises(HTTPException):
        await product_service.get_by_barcode(a, "222")
    # A's own barcode still resolves for A.
    assert (await product_service.get_by_barcode(a, "111"))["id"] == pa["id"]


async def test_orders_service_isolation():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    await tenant_db(a)[Collections.ORDERS].insert_one(
        {"erp_order_number": "1001", "status": "imported", "lines": []}
    )
    ob = await tenant_db(b)[Collections.ORDERS].insert_one(
        {"erp_order_number": "9001", "status": "imported", "lines": []}
    )

    orders_a = await order_service.list_orders(a)
    assert {o["erp_order_number"] for o in orders_a["items"]} == {"1001"}
    with pytest.raises(HTTPException):
        await order_service.get_order(a, str(ob.inserted_id))


async def test_inventory_balances_isolation():
    a = await _make_tenant("A")
    b = await _make_tenant("B")
    wa = await _make_warehouse(a, "WH-A")
    wb = await _make_warehouse(b, "WH-B")
    await _seed_balance(a, "pa", wa, "la", 10)
    await _seed_balance(b, "pb", wb, "lb", 99)

    balances_a = (await inventory_service.list_balances(a, user=_admin(a)))["items"]
    assert len(balances_a) == 1
    assert balances_a[0]["warehouse_id"] == wa


# ---------------------------------------------------------------------------
# 3. allowed_warehouse_ids enforcement
# ---------------------------------------------------------------------------
async def test_warehouse_scope_filters_reads():
    a = await _make_tenant("A")
    wh1 = await _make_warehouse(a, "WH-1")
    wh2 = await _make_warehouse(a, "WH-2")
    await _seed_balance(a, "p1", wh1, "l1", 5)
    await _seed_balance(a, "p2", wh2, "l2", 7)

    operator = _operator(a, [wh1])
    admin = _admin(a)

    # Operator restricted to wh1 sees only wh1.
    ops_balances = (await inventory_service.list_balances(a, user=operator))["items"]
    assert {b["warehouse_id"] for b in ops_balances} == {wh1}
    ops_warehouses = await warehouse_service.list_warehouses(a, operator)
    assert {w["id"] for w in ops_warehouses} == {wh1}

    # Admin (supervisor role) bypasses the restriction.
    admin_balances = (await inventory_service.list_balances(a, user=admin))["items"]
    assert {b["warehouse_id"] for b in admin_balances} == {wh1, wh2}
    admin_warehouses = await warehouse_service.list_warehouses(a, admin)
    assert {w["id"] for w in admin_warehouses} == {wh1, wh2}


async def test_warehouse_scope_empty_list_means_all():
    a = await _make_tenant("A")
    wh1 = await _make_warehouse(a, "WH-1")
    wh2 = await _make_warehouse(a, "WH-2")
    # Operator with NO restriction configured -> sees everything.
    operator = _operator(a, [])
    warehouses = await warehouse_service.list_warehouses(a, operator)
    assert {w["id"] for w in warehouses} == {wh1, wh2}


async def test_warehouse_scope_blocks_operation_and_reads_of_other_warehouse():
    a = await _make_tenant("A")
    wh1 = await _make_warehouse(a, "WH-1")
    wh2 = await _make_warehouse(a, "WH-2")
    operator = _operator(a, [wh1])

    # A picking task in wh2 is invisible and cannot be opened by a wh1 operator.
    task = await tenant_db(a)[Collections.PICKING_TASKS].insert_one(
        {"order_id": "o1", "warehouse_id": wh2, "assigned_to": operator.id, "status": "pending", "lines": []}
    )
    tid = str(task.inserted_id)

    assert (await picking_service.list_tasks(a, operator))["items"] == []
    with pytest.raises(HTTPException) as exc:
        await picking_service.get_task(a, tid, operator)
    assert exc.value.status_code == 403

    # assert_warehouse_allowed is the primitive behind it.
    with pytest.raises(HTTPException):
        operator.assert_warehouse_allowed(wh2)
    operator.assert_warehouse_allowed(wh1)  # allowed -> no raise


# ---------------------------------------------------------------------------
# 4. Regression guard: no raw get_database() in request-scoped services
# ---------------------------------------------------------------------------
async def test_request_scoped_services_do_not_use_raw_get_database():
    services_dir = Path(__file__).resolve().parents[1] / "services"
    # login is pre-authentication (no tenant yet) and is allowed to stay raw.
    allowed_raw = {"auth_service.py"}
    offenders = []
    for path in services_dir.glob("*.py"):
        if path.name in allowed_raw or path.name == "__init__.py":
            continue
        if "get_database(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], (
        f"These services reach the un-scoped database directly; use tenant_db(): {offenders}"
    )
