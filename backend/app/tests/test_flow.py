"""End-to-end backend flow test against an in-memory Mongo (DEFONTANA_MOCK)."""
import pytest

from app.core.config import settings
from app.core.database import get_database
from app.integrations.defontana.mock_data import MOCK_PRODUCTS
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, _load_catalog, run_seed
from app.services import (
    auth_service,
    dispatch_service,
    integration_service,
    inventory_service,
    order_service,
    packing_service,
    picking_service,
    product_service,
)
from app.workers import sync_worker
from .conftest import make_user

pytestmark = pytest.mark.asyncio

BAD_BARCODE = "000000000000"


async def _admin_user():
    db = get_database()
    return await db[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL})


async def _order_1001():
    db = get_database()
    return await db[Collections.ORDERS].find_one({"erp_order_number": "1001"})


async def _barcode_for(tenant_id, product_id):
    db = get_database()
    bc = await db[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "product_id": product_id}
    )
    return bc["barcode"]


async def _order_scan_plan(tenant_id):
    """Return (order, [(barcode, ordered_quantity), ...]) for order 1001's lines.

    Derived from the seeded data so the flow stays valid regardless of which
    catalog products back the demo order.
    """
    order = await _order_1001()
    plan = []
    for line in order["lines"]:
        barcode = await _barcode_for(tenant_id, line["product_id"])
        plan.append((barcode, line["ordered_quantity"]))
    return order, plan


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
    catalog = _load_catalog()

    # The whole in-stock catalog is seeded.
    db = get_database()
    count = await db[Collections.PRODUCTS].count_documents({"tenant_id": tenant_id})
    assert count == len(catalog)

    listed = await product_service.list_products(tenant_id)
    assert listed["items"]  # listing returns rows (capped at 500 against real Mongo)
    assert listed["total"] == count  # envelope reports the full count, not just the page

    first = catalog[0]
    found = await product_service.get_by_barcode(tenant_id, first["barcode"])
    assert found["sku"] == first["sku"]


async def test_full_picking_packing_dispatch_flow():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin_doc = await _admin_user()
    admin = make_user(admin_doc)

    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    # 1. Generate picking task from the order.
    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    task_id = task["id"]
    assert task["status"] == "pending"

    # 2. A wrong barcode is rejected (section 8.1).
    rejected = await picking_service.scan(tenant_id, task_id, admin, BAD_BARCODE, 1, None)
    assert rejected["status"] == "rejected"

    # 3. Scan the right products in full.
    ok1 = await picking_service.scan(tenant_id, task_id, admin, bc1, q1, None)
    assert ok1["status"] == "ok"
    ok2 = await picking_service.scan(tenant_id, task_id, admin, bc2, q2, None)
    assert ok2["status"] == "ok"

    # 4. Complete picking -> packing task auto-created.
    completed = await picking_service.complete(tenant_id, task_id, admin)
    assert completed["status"] == "completed"

    packing_tasks = (await packing_service.list_tasks(tenant_id, admin))["items"]
    assert len(packing_tasks) == 1
    packing_id = packing_tasks[0]["id"]

    # 5. Packing: start, re-scan, complete -> order ready_to_dispatch.
    await packing_service.start_task(tenant_id, packing_id, admin)
    await packing_service.scan(tenant_id, packing_id, admin, bc1, q1, None)
    await packing_service.scan(tenant_id, packing_id, admin, bc2, q2, None)
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
    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, bc1, q1, None)
    await picking_service.scan(tenant_id, task["id"], admin, bc2, q2, None)
    await picking_service.complete(tenant_id, task["id"], admin)
    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    await packing_service.scan(tenant_id, pk["id"], admin, bc1, q1, None)
    await packing_service.scan(tenant_id, pk["id"], admin, bc2, q2, None)
    await packing_service.complete(tenant_id, pk["id"], admin)

    await dispatch_service.confirm_dispatch(tenant_id, order_id, admin)
    with pytest.raises(Exception):
        await dispatch_service.confirm_dispatch(tenant_id, order_id, admin)


async def test_picking_over_scan_blocked():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order = await _order_1001()
    order_id = str(order["_id"])
    line0 = order["lines"][0]
    bc1 = await _barcode_for(tenant_id, line0["product_id"])
    qty1 = line0["ordered_quantity"]

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    tid = task["id"]

    ok = await picking_service.scan(tenant_id, tid, admin, bc1, qty1, None)
    assert ok["status"] == "ok"

    # One more scan of the same (already complete) product must be blocked.
    over = await picking_service.scan(tenant_id, tid, admin, bc1, 1, None)
    assert over["status"] == "rejected"
    assert over["feedback"] == "warning"

    # Nothing was applied: the picked quantity stays at the required amount.
    t = await picking_service.get_task(tenant_id, tid)
    line = next(l for l in t["lines"] if l["sku"] == line0["sku"])
    assert line["quantity_picked"] == qty1


async def test_picking_reset_line():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order = await _order_1001()
    order_id = str(order["_id"])
    sku1 = order["lines"][0]["sku"]
    bc1 = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    qty1 = order["lines"][0]["ordered_quantity"]

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    tid = task["id"]
    await picking_service.scan(tenant_id, tid, admin, bc1, qty1, None)

    t = await picking_service.get_task(tenant_id, tid)
    line = next(l for l in t["lines"] if l["sku"] == sku1)
    assert line["quantity_picked"] == qty1  # fully picked

    # Reset the line (fix a mistake) -> back to zero / pending.
    t = await picking_service.reset_line(tenant_id, tid, admin, sku1)
    line = next(l for l in t["lines"] if l["sku"] == sku1)
    assert line["quantity_picked"] == 0
    assert line["status"] == "pending"

    # It can be scanned again.
    res = await picking_service.scan(tenant_id, tid, admin, bc1, qty1, None)
    assert res["status"] == "ok"


async def test_packing_reset_line():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    # Drive picking to completion so a packing task exists.
    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, bc1, q1, None)
    await picking_service.scan(tenant_id, task["id"], admin, bc2, q2, None)
    await picking_service.complete(tenant_id, task["id"], admin)

    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    pid = pk["id"]
    sku1 = pk["lines"][0]["sku"]
    await packing_service.start_task(tenant_id, pid, admin)
    pkg = await packing_service.create_package(tenant_id, pid, admin, None)
    await packing_service.scan(tenant_id, pid, admin, bc1, q1, pkg["package_id"])

    t = await packing_service.get_task(tenant_id, pid)
    line = next(l for l in t["lines"] if l["sku"] == sku1)
    assert line["quantity_packed"] == q1
    assert any(it.get("sku") == sku1 for p in t["packages"] for it in p.get("items", []))

    # Reset -> line back to 0 and its items removed from every package.
    t = await packing_service.reset_line(tenant_id, pid, admin, sku1)
    line = next(l for l in t["lines"] if l["sku"] == sku1)
    assert line["quantity_packed"] == 0
    assert all(it.get("sku") != sku1 for p in t["packages"] for it in p.get("items", []))


async def test_create_product_without_erp_sync():
    """Stand-alone: con ERP_SYNC_ENABLED=false no se encola nada al ERP."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())

    p = await product_service.create_product(
        tenant_id, {"sku": "LOCAL-001", "name": "Producto local"}, admin.id
    )
    assert p["sku"] == "LOCAL-001"

    db = get_database()
    assert await db[Collections.SYNC_JOBS].find_one({"job_type": "create_product"}) is None


async def test_create_product_and_sync_job(monkeypatch):
    monkeypatch.setattr(settings, "erp_sync_enabled", True)
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())

    p = await product_service.create_product(
        tenant_id,
        {"sku": "NEW-001", "name": "Producto Nuevo Demo", "category": "Test", "barcode": "1234567890123"},
        admin.id,
    )
    assert p["sku"] == "NEW-001"
    assert any(b["barcode"] == "1234567890123" for b in p["barcodes"])

    db = get_database()
    job = await db[Collections.SYNC_JOBS].find_one({"job_type": "create_product"})
    assert job is not None
    await sync_worker.process_job(job)
    job_after = await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    assert job_after["status"] == "success"

    # Duplicate SKU is rejected.
    with pytest.raises(Exception):
        await product_service.create_product(tenant_id, {"sku": "NEW-001", "name": "x"}, admin.id)


async def test_create_reception_adds_stock_and_syncs(monkeypatch):
    monkeypatch.setattr(settings, "erp_sync_enabled", True)
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())

    db = get_database()
    bal = await db[Collections.INVENTORY_BALANCES].find_one({"tenant_id": tenant_id})
    product_id = bal["product_id"]
    warehouse_id = bal["warehouse_id"]
    location_id = bal["location_id"]
    before = bal["quantity_on_hand"]

    result = await inventory_service.create_reception(
        tenant_id=tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        quantity=7,
        created_by=admin.id,
        reference="PO-DEMO-1",
    )
    assert result["movement"]["movement_type"] == "receipt"

    after_doc = await inventory_service.get_balance_doc(
        tenant_id, product_id, warehouse_id, location_id
    )
    assert after_doc["quantity_on_hand"] == before + 7

    job = await db[Collections.SYNC_JOBS].find_one({"job_type": "create_inventory_document"})
    assert job is not None
    await sync_worker.process_job(job)
    job_after = await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    assert job_after["status"] == "success"


async def test_products_pagination():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    page1 = await product_service.list_products(tenant_id, limit=10, offset=0)
    page2 = await product_service.list_products(tenant_id, limit=10, offset=10)
    # Envelope carries paging metadata so the UI can render "X–Y de N".
    assert page1["limit"] == 10 and page1["offset"] == 0
    assert page2["offset"] == 10
    assert page1["total"] == page2["total"] >= 20
    items1, items2 = page1["items"], page2["items"]
    assert len(items1) == 10
    assert len(items2) == 10
    assert {p["id"] for p in items1}.isdisjoint({p["id"] for p in items2})


async def test_user_cannot_lock_himself_out():
    """Nadie puede desactivarse ni bajarse el rol a sí mismo (te deja fuera al instante)."""
    from app.models.user import UserRole
    from app.schemas.auth import UserUpdate
    from app.services import user_service

    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin_doc = await _admin_user()
    admin_id = str(admin_doc["_id"])

    with pytest.raises(Exception):
        await user_service.update_user(
            tenant_id, admin_id, UserUpdate(is_active=False), admin_id
        )
    with pytest.raises(Exception):
        await user_service.update_user(
            tenant_id, admin_id, UserUpdate(role=UserRole.PICKER), admin_id
        )

    # Sigue activo y siendo admin.
    still = await user_service.get_user(tenant_id, admin_id)
    assert still["is_active"] is True
    assert still["role"] == "admin"


async def test_update_user_name_and_email():
    """Se puede editar nombre y correo; el correo duplicado se rechaza."""
    from app.models.user import UserRole
    from app.schemas.auth import UserCreate, UserUpdate
    from app.services import user_service

    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin_doc = await _admin_user()
    actor = str(admin_doc["_id"])

    creado = await user_service.create_user(
        tenant_id,
        UserCreate(name="Operario Uno", email="op1@demo.cl", password="clave123", role=UserRole.PICKER),
        actor,
    )
    uid = creado["id"]

    # Editar nombre y correo.
    upd = await user_service.update_user(
        tenant_id, uid, UserUpdate(name="Operario Editado", email="nuevo@demo.cl"), actor
    )
    assert upd["name"] == "Operario Editado"
    assert upd["email"] == "nuevo@demo.cl"

    # Un correo ya usado por otro usuario se rechaza.
    with pytest.raises(Exception):
        await user_service.update_user(
            tenant_id, uid, UserUpdate(email=DEMO_ADMIN_EMAIL), actor
        )


async def test_edit_order_only_before_picking():
    """El pedido se puede editar en 'imported'; una vez con picking, se bloquea."""
    from app.core.database import get_database as _gdb
    from app.models.order import OrderStatus
    from app.schemas.order import OrderLineInput, OrderUpdate

    # importar el handler de la ruta directamente
    from app.api.routes.orders import update_order

    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order = await _order_1001()
    order_id = str(order["_id"])
    sku0 = order["lines"][0]["sku"]

    # Editar: cambiar cliente y dejar una sola línea con cantidad nueva.
    upd = await update_order(
        order_id,
        OrderUpdate(customer="Cliente Editado", lines=[OrderLineInput(sku=sku0, ordered_quantity=9)]),
        admin,
    )
    assert upd["customer"] == "Cliente Editado"
    assert len(upd["lines"]) == 1
    assert upd["lines"][0]["ordered_quantity"] == 9

    # Generar picking -> el pedido deja de estar 'imported'.
    await order_service.create_picking_task(tenant_id, order_id, admin.id)
    o2 = await order_service.get_order(tenant_id, order_id)
    assert o2["status"] != OrderStatus.IMPORTED.value

    # Ahora editar debe fallar.
    with pytest.raises(Exception):
        await update_order(order_id, OrderUpdate(customer="x"), admin)


async def test_defontana_mock_sync_products():
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    result = await integration_service.run_sync_products(tenant_id, admin.id)
    assert result["status"] == "ok"
    assert result["summary"]["synced"] == len(MOCK_PRODUCTS)


async def test_dashboard_stats():
    from app.services import dashboard_service

    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    stats = await dashboard_service.get_stats(tenant_id)

    catalog = _load_catalog()
    assert stats["inventory"]["productos"] == len(catalog)
    assert stats["inventory"]["con_stock"] >= 1  # el seed carga stock
    assert stats["inventory"]["sin_stock"] >= 0
    assert stats["inventory"]["ubicaciones"] >= 1

    o = stats["orders"]
    assert set(o) >= {
        "total", "por_procesar", "en_proceso", "listos_despacho",
        "despachados", "despachados_hoy", "error_cancelados", "por_estado",
    }
    # El desglose por estado suma el total.
    assert sum(o["por_estado"].values()) == o["total"]
    assert set(stats["operations"]) == {"picking_abiertas", "packing_abiertas", "sync_pendientes"}


async def test_update_location():
    from app.models.location import LocationType
    from app.schemas.warehouse import LocationCreate, LocationUpdate
    from app.services import warehouse_service

    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    db = get_database()
    wh = await db[Collections.WAREHOUSES].find_one({"tenant_id": tenant_id})
    wid = str(wh["_id"])

    loc = await warehouse_service.create_location(
        tenant_id,
        LocationCreate(warehouse_id=wid, code="EDIT-1", name="Orig", type=LocationType.STORAGE),
        admin.id,
    )

    # Editar nombre, tipo, zona y desactivar.
    upd = await warehouse_service.update_location(
        tenant_id,
        loc["id"],
        LocationUpdate(name="Nuevo", type=LocationType.PICKING, zone="Z1", is_active=False),
        admin.id,
    )
    assert upd["name"] == "Nuevo"
    assert upd["type"] == "picking"
    assert upd["zone"] == "Z1"
    assert upd["is_active"] is False

    # Un código repetido en la misma bodega se rechaza.
    await warehouse_service.create_location(
        tenant_id, LocationCreate(warehouse_id=wid, code="EDIT-2"), admin.id
    )
    with pytest.raises(Exception):
        await warehouse_service.update_location(
            tenant_id, loc["id"], LocationUpdate(code="EDIT-2"), admin.id
        )

    # Renombrar el código a uno libre funciona.
    ok = await warehouse_service.update_location(
        tenant_id, loc["id"], LocationUpdate(code="EDIT-1B"), admin.id
    )
    assert ok["code"] == "EDIT-1B"


async def test_cannot_regenerate_picking_after_completed():
    """Un pedido ya pickeado (picked/packing/…) no debe poder generar picking otra vez."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, bc1, q1, None)
    await picking_service.scan(tenant_id, task["id"], admin, bc2, q2, None)
    await picking_service.complete(tenant_id, task["id"], admin)

    o = await order_service.get_order(tenant_id, order_id)
    assert o["status"] == "picked"
    with pytest.raises(Exception):
        await order_service.create_picking_task(tenant_id, order_id, admin.id)


async def test_revert_flow_dispatch_packing_picking():
    """Cadena de retroceso: anular despacho -> reabrir packing -> reabrir picking."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    # Llevar hasta despachado.
    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    await picking_service.scan(tenant_id, task["id"], admin, bc1, q1, None)
    await picking_service.scan(tenant_id, task["id"], admin, bc2, q2, None)
    await picking_service.complete(tenant_id, task["id"], admin)
    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    await packing_service.scan(tenant_id, pk["id"], admin, bc1, q1, None)
    await packing_service.scan(tenant_id, pk["id"], admin, bc2, q2, None)
    await packing_service.complete(tenant_id, pk["id"], admin)
    d1 = await dispatch_service.confirm_dispatch(tenant_id, order_id, admin, guide_number="GD-123")
    assert d1["guide_number"] == "GD-123"
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "dispatched"

    # Anular despacho -> ready_to_dispatch, y se puede re-despachar.
    await dispatch_service.cancel_dispatch(tenant_id, order_id, admin)
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "ready_to_dispatch"
    d2 = await dispatch_service.confirm_dispatch(tenant_id, order_id, admin)
    assert d2["status"] == "pending"
    await dispatch_service.cancel_dispatch(tenant_id, order_id, admin)

    # Reabrir packing -> packing.
    await packing_service.reopen_packing(tenant_id, order_id, admin)
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "packing"

    # Reabrir picking -> picking, y la tarea de packing queda cancelada.
    await picking_service.reopen_picking(tenant_id, order_id, admin)
    assert (await order_service.get_order(tenant_id, order_id))["status"] == "picking"
    db = get_database()
    pk_after = await db[Collections.PACKING_TASKS].find_one(
        {"tenant_id": tenant_id, "order_id": order_id}
    )
    assert pk_after["status"] == "cancelled"


async def test_reopen_restores_inventory():
    """Reabrir picking revierte el movimiento de inventario (la ubicación de origen
    recupera su stock) y al recompletar no se descuenta dos veces."""
    seed = await run_seed()
    tenant_id = seed["tenant_id"]
    admin = make_user(await _admin_user())
    order, plan = await _order_scan_plan(tenant_id)
    order_id = str(order["_id"])
    (bc1, q1), (bc2, q2) = plan[0], plan[1]

    task = await order_service.create_picking_task(tenant_id, order_id, admin.id)
    line0 = next(l for l in task["lines"] if l.get("barcode_expected") and bc1 in l["barcode_expected"])
    pid, loc, wh = line0["product_id"], line0["suggested_location_id"], task["warehouse_id"]
    before = (await inventory_service.get_balance_doc(tenant_id, pid, wh, loc))["quantity_on_hand"]

    await picking_service.scan(tenant_id, task["id"], admin, bc1, q1, None)
    await picking_service.scan(tenant_id, task["id"], admin, bc2, q2, None)
    await picking_service.complete(tenant_id, task["id"], admin)
    after_pick = (await inventory_service.get_balance_doc(tenant_id, pid, wh, loc))["quantity_on_hand"]
    assert after_pick == before - q1  # el pick descontó la ubicación de origen

    await picking_service.reopen_picking(tenant_id, order_id, admin)
    restored = (await inventory_service.get_balance_doc(tenant_id, pid, wh, loc))["quantity_on_hand"]
    assert restored == before  # el reverso devolvió el stock

    # Recompletar el picking descuenta una sola vez (no se duplica).
    await picking_service.complete(tenant_id, task["id"], admin)
    final = (await inventory_service.get_balance_doc(tenant_id, pid, wh, loc))["quantity_on_hand"]
    assert final == before - q1
