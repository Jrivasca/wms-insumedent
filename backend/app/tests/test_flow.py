"""End-to-end backend flow test against an in-memory Mongo (DEFONTANA_MOCK)."""
import pytest

from app.core.database import get_database
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, run_seed
from app.services import (
    auth_service,
    dispatch_service,
    integration_service,
    order_service,
    packing_service,
    picking_service,
    product_service,
)
from app.workers import sync_worker
from .conftest import make_user

pytestmark = pytest.mark.asyncio

BC_SKU001 = "780000000001"
BC_SKU002 = "780000000002"
BAD_BARCODE = "000000000000"


async def _admin_user():
    db = get_database()
    return await db[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL})


async def _order_1001():
    db = get_database()
    return await db[Collections.ORDERS].find_one({"erp_order_number": "1001"})


async def test_seed_is_idempotent():
    first = await run_seed()
    assert first["status"] == "seeded"
    second = await run_seed()
    assert second["status"] == "already_seeded"
    assert first["tenant_id"] == second["tenant_id"]


async def test_login_and_products():
    await run_seed()
    result = await auth_service.login(DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD)
    assert result["access_token"]
    assert result["user"]["role"] == "admin"

    tenant_id = result["user"]["tenant_id"]
    products = await product_service.list_products(tenant_id)
    assert len(products) == 3

    found = await product_service.get_by_barcode(tenant_id, BC_SKU001)
    assert found["sku"] == "SKU001"


async def test_full_picking_packing_dispatch_flow():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin_doc = await _admin_user()
    admin = make_user(admin_doc)

    order = await _order_1001()
    order_id = str(order["_id"])

    # 1. Generate picking task from the order.
    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    task_id = task["id"]
    assert task["status"] == "pending"

    # 2. A wrong barcode is rejected (section 8.1).
    rejected = await picking_service.scan(tenant_id, task_id, admin, BAD_BARCODE, 1, None)
    assert rejected["status"] == "rejected"

    # 3. Scan the right products in full.
    ok1 = await picking_service.scan(tenant_id, task_id, admin, BC_SKU001, 3, None)
    assert ok1["status"] == "ok"
    ok2 = await picking_service.scan(tenant_id, task_id, admin, BC_SKU002, 2, None)
    assert ok2["status"] == "ok"

    # 4. Complete picking -> packing task auto-created.
    completed = await picking_service.complete(tenant_id, task_id, admin)
    assert completed["status"] == "completed"

    packing_tasks = await packing_service.list_tasks(tenant_id, admin)
    assert len(packing_tasks) == 1
    packing_id = packing_tasks[0]["id"]

    # 5. Packing: start, re-scan, complete -> order ready_to_dispatch.
    await packing_service.start_task(tenant_id, packing_id, admin)
    await packing_service.scan(tenant_id, packing_id, admin, BC_SKU001, 3, None)
    await packing_service.scan(tenant_id, packing_id, admin, BC_SKU002, 2, None)
    packed = await packing_service.complete(tenant_id, packing_id, admin)
    assert packed["status"] == "completed"

    order_after = await order_service.get_order(tenant_id, order_id)
    assert order_after["status"] == "ready_to_dispatch"

    # 6. Confirm dispatch -> creates a dispatch_order sync job.
    dispatch = await dispatch_service.confirm_dispatch(tenant_id, order_id, admin, "Starken", "TRK-1")
    assert dispatch["status"] == "pending"

    db = get_database()
    job = await db[Collections.SYNC_JOBS].find_one({"job_type": "dispatch_order"})
    assert job is not None

    # 7. Worker processes the job (mock Defontana) -> success + dispatch completed.
    await sync_worker.process_job(job)
    job_after = await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    assert job_after["status"] == "success"

    dispatch_after = await dispatch_service.get_dispatch(tenant_id, dispatch["id"])
    assert dispatch_after["status"] == "completed"


async def test_double_dispatch_blocked():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order = await _order_1001()
    order_id = str(order["_id"])

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, BC_SKU001, 3, None)
    await picking_service.scan(tenant_id, task["id"], admin, BC_SKU002, 2, None)
    await picking_service.complete(tenant_id, task["id"], admin)
    pk = (await packing_service.list_tasks(tenant_id, admin))[0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    await packing_service.scan(tenant_id, pk["id"], admin, BC_SKU001, 3, None)
    await packing_service.scan(tenant_id, pk["id"], admin, BC_SKU002, 2, None)
    await packing_service.complete(tenant_id, pk["id"], admin)

    await dispatch_service.confirm_dispatch(tenant_id, order_id, admin)
    with pytest.raises(Exception):
        await dispatch_service.confirm_dispatch(tenant_id, order_id, admin)


async def test_defontana_mock_sync_products():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    result = await integration_service.run_sync_products(tenant_id, admin.id)
    assert result["status"] == "ok"
    assert result["summary"]["synced"] == 3
