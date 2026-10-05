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
