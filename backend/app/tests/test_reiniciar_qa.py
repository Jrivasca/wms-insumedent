"""Reinicio de pruebas QA: el stock vuelve a como estaba antes de las pruebas.

Caso real (2026-10-05): el reinicio de los lunes borraba pedidos y tareas pero dejaba en
STAGING/PACKING lo que las pruebas movieron, con saldos negativos.
"""
import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.maintenance import reiniciar_qa
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import dispatch_service

from .conftest import make_user
from .test_split_dispatch import _drive_to_ready

pytestmark = pytest.mark.asyncio


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _saldos(tenant_id):
    return {
        (b["location_id"], b["product_id"], b.get("lot_number")): b.get("quantity_on_hand", 0)
        async for b in tenant_db(tenant_id)[Collections.INVENTORY_BALANCES].find({})
    }


def _iguales(a, b):
    claves = set(a) | set(b)
    return all(abs(a.get(k, 0) - b.get(k, 0)) < 1e-9 for k in claves)


async def test_revertir_huerfanos_deja_el_stock_como_antes():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    antes = await _saldos(tenant_id)

    oid, (sku0, sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])
    await dispatch_service.confirm_dispatch(
        tenant_id, oid, admin, lines=[{"sku": sku0, "quantity": 5}, {"sku": sku1, "quantity": 3}]
    )
    assert not _iguales(antes, await _saldos(tenant_id))

    # Lo que hacía el reinicio viejo: borrar sin tocar el stock.
    db = tenant_db(tenant_id)
    for col in reiniciar_qa.COLECCIONES_PEDIDOS:
        await db[col].delete_many({})

    movs = await reiniciar_qa.movimientos_a_revertir(tenant_id, solo_huerfanos=True)
    assert movs, "debería haber movimientos huérfanos"
    await reiniciar_qa.revertir(tenant_id, movs)

    assert _iguales(antes, await _saldos(tenant_id))
    # Idempotente: una segunda pasada no encuentra nada.
    assert await reiniciar_qa.movimientos_a_revertir(tenant_id, solo_huerfanos=True) == []


async def test_sin_reset_no_toca_lo_que_tiene_tarea_viva():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    await _drive_to_ready(tenant_id, admin, [2, 1])
    assert await reiniciar_qa.movimientos_a_revertir(tenant_id, solo_huerfanos=True) == []
    assert await reiniciar_qa.movimientos_a_revertir(tenant_id, solo_huerfanos=False)


async def test_reset_semanal_revierte_borra_y_resincroniza(monkeypatch):
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    antes = await _saldos(tenant_id)
    await _drive_to_ready(tenant_id, admin, [2, 1])

    llamado = {}

    async def fake_sync(t):
        llamado["tenant"] = t
        return {"created": 0}

    from app.integrations.defontana import order_sync
    monkeypatch.setattr(order_sync, "sync_orders", fake_sync)

    await reiniciar_qa.main(tenant_id, apply=True, reset_semanal=True)

    db = tenant_db(tenant_id)
    assert await db[Collections.ORDERS].count_documents({}) == 0
    assert await db[Collections.PICKING_TASKS].count_documents({}) == 0
    assert llamado["tenant"] == tenant_id
    assert _iguales(antes, await _saldos(tenant_id))


async def test_dry_run_no_cambia_nada():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    await _drive_to_ready(tenant_id, admin, [2, 1])
    for col in reiniciar_qa.COLECCIONES_PEDIDOS:
        await tenant_db(tenant_id)[col].delete_many({})
    medio = await _saldos(tenant_id)
    await reiniciar_qa.main(tenant_id, apply=False, reset_semanal=False)
    assert _iguales(medio, await _saldos(tenant_id))


async def test_con_lote_tambien_vuelve_y_no_quedan_negativos():
    """El caso real: el pack no lleva lote y deja +q/−q en STAGING; la reversa lo cuadra."""
    from app.services import packing_service, picking_service

    from .test_picking_lots import _setup

    s = await _setup()
    admin = make_user({"_id": "admin-1", "tenant_id": s.tenant_id, "role": "admin"})
    # Saldos de ANTES del picking (el _setup ya creó la tarea, que no mueve stock).
    antes = await _saldos(s.tenant_id)
    order = await s.db[Collections.ORDERS].find_one({"erp_order_number": "9101"})

    await picking_service.scan(s.tenant_id, s.task_id, s.picker, s.bc, 3, s.loc_id, "LOTE-B")
    await picking_service.complete(s.tenant_id, s.task_id, s.picker)
    pk = (await packing_service.list_tasks(s.tenant_id, admin))["items"][0]
    await packing_service.start_task(s.tenant_id, pk["id"], admin)
    pkg = (await packing_service.create_package(s.tenant_id, pk["id"], admin, None))["package_id"]
    await packing_service.scan(s.tenant_id, pk["id"], admin, s.bc, 3, pkg)
    await packing_service.complete(s.tenant_id, pk["id"], admin)
    await dispatch_service.confirm_dispatch(s.tenant_id, str(order["_id"]), admin)

    for col in reiniciar_qa.COLECCIONES_PEDIDOS:
        await s.db[col].delete_many({})
    await reiniciar_qa.revertir(
        s.tenant_id, await reiniciar_qa.movimientos_a_revertir(s.tenant_id, solo_huerfanos=True)
    )

    despues = await _saldos(s.tenant_id)
    assert _iguales(antes, despues)
    assert all(q >= 0 for q in despues.values())


# ---------------------------------------------------------------------------
# Vaciar operativas (el caso del 2026-10-05, con correcciones manuales entre medio)
# ---------------------------------------------------------------------------
async def _ubic(db, warehouse_id, tipo):
    loc = await db[Collections.LOCATIONS].find_one({"warehouse_id": warehouse_id, "type": tipo})
    return str(loc["_id"])


async def _poner(db, tenant_id, pid, wh, loc, lot, q):
    await db[Collections.INVENTORY_BALANCES].insert_one(
        {"tenant_id": tenant_id, "product_id": pid, "warehouse_id": wh, "location_id": loc,
         "lot_number": lot, "quantity_on_hand": q, "quantity_reserved": 0, "quantity_blocked": 0}
    )


async def test_vaciar_operativas_deja_todo_en_cero():
    tenant_id = (await run_seed())["tenant_id"]
    db = tenant_db(tenant_id)
    wh = str((await db[Collections.WAREHOUSES].find_one({}))["_id"])
    staging = await _ubic(db, wh, "staging")
    packing = await _ubic(db, wh, "packing")
    origen = await _ubic(db, wh, "storage")
    prods = [str(p["_id"]) async for p in db[Collections.PRODUCTS].find({}).limit(4)]
    for pid in prods:
        await db[Collections.INVENTORY_BALANCES].delete_many({"product_id": pid})
    a, b, c, d = prods
    # a: el bug del lote (+30 con lote / −30 sin lote): se cuadra sin mover cantidades.
    await _poner(db, tenant_id, a, wh, staging, "L1", 30)
    await _poner(db, tenant_id, a, wh, staging, None, -30)
    # b: quedó pickeado sin pedido: vuelve al origen.
    await _poner(db, tenant_id, b, wh, staging, "L2", 6)
    await _poner(db, tenant_id, b, wh, origen, "L2", 10)
    # c: quedó empacado sin pedido: vuelve al origen.
    await _poner(db, tenant_id, c, wh, packing, None, 2)
    # d: negativo suelto (la corrección manual ya devolvió de más): se repone desde el origen.
    await _poner(db, tenant_id, d, wh, staging, None, -1)
    await _poner(db, tenant_id, d, wh, origen, "L4", 3)

    plan = await reiniciar_qa.plan_vaciar(tenant_id)
    assert plan["sin_resolver"] == []
    await reiniciar_qa.vaciar(tenant_id, plan["acciones"])

    s = await _saldos(tenant_id)
    for (loc, pid, _lot), q in s.items():
        if loc in (staging, packing) and pid in prods:
            assert abs(q) < 1e-9, (loc, pid, _lot, q)
    assert s[(origen, b, "L2")] == 16
    assert s[(origen, c, None)] == 2
    assert s[(origen, d, "L4")] == 2  # repuso 1
    # Todo quedó con movimiento (nada de cambios de saldo sin rastro).
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents(
        {"reference_type": "mantencion"}) >= 6
    # Idempotente: una segunda pasada no tiene nada que hacer.
    assert (await reiniciar_qa.plan_vaciar(tenant_id))["acciones"] == []


async def test_no_revierte_si_dejaria_negativos():
    """Caso DAGUJA011: el despacho se corrigió a mano después; revertir daría −18."""
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, sku1) = await _drive_to_ready(tenant_id, admin, [2, 1])
    db = tenant_db(tenant_id)
    # Corrección manual: alguien vació a mano el packing (sin pasar por la reversa).
    await db[Collections.INVENTORY_BALANCES].update_many(
        {"location_id": await _ubic(db, (await db[Collections.WAREHOUSES].find_one({}))["_id"].__str__(), "packing")},
        {"$set": {"quantity_on_hand": 0}},
    )
    for col in reiniciar_qa.COLECCIONES_PEDIDOS:
        await db[col].delete_many({})
    movs = await reiniciar_qa.movimientos_a_revertir(tenant_id, solo_huerfanos=True)
    assert await reiniciar_qa.negativos_tras_revertir(tenant_id, movs)
