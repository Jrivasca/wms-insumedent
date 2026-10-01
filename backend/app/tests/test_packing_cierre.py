"""Cierre de un packing con faltantes: queda pendiente salvo que un supervisor lo cierre.

Decisión del dueño (2026-10-01): «Finalizar packing» con faltantes respecto a lo pickeado
deja la tarea pendiente para todos, también para el supervisor y el administrador. Cerrar así
es una acción aparte (``force_close``) que solo ellos pueden tomar.
"""
import pytest
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.utils import to_object_id
from app.models import Collections
from app.models.packing import PackingTaskStatus
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import order_service, packing_service, picking_service

from .conftest import make_user
from .test_split_dispatch import _barcode_for, _make_order

pytestmark = pytest.mark.asyncio


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _packing_con_faltante(tenant_id: str, admin, number: str) -> tuple[str, str]:
    """Pedido de 5+3 pickeado entero y empacado con una unidad menos. Devuelve (pedido, tarea)."""
    order = await _make_order(tenant_id, [5, 3], number=number)
    bcs = [await _barcode_for(tenant_id, ln["product_id"]) for ln in order["lines"]]
    pick = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    for bc, q in zip(bcs, [5, 3]):
        await picking_service.scan(tenant_id, pick["id"], admin, bc, q, None)
    await picking_service.complete(tenant_id, pick["id"], admin)

    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    pkg = (await packing_service.create_package(tenant_id, pk["id"], admin, None))["package_id"]
    for bc, q in zip(bcs, [4, 3]):
        await packing_service.scan(tenant_id, pk["id"], admin, bc, q, pkg)
    return order["id"], pk["id"]


async def test_finalizar_con_faltantes_deja_pendiente_aunque_sea_admin():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, tid = await _packing_con_faltante(tenant_id, admin, "9600")

    with pytest.raises(HTTPException) as exc:
        await packing_service.complete(tenant_id, tid, admin)
    assert exc.value.status_code == 409

    tarea = await packing_service.get_task(tenant_id, tid, admin)
    assert tarea["status"] == PackingTaskStatus.OBSERVED.value
    pedido = await order_service.get_order(tenant_id, oid)
    assert pedido["status"] != "ready_to_dispatch"


async def test_supervisor_cierra_con_faltantes_de_forma_explicita():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, tid = await _packing_con_faltante(tenant_id, admin, "9601")

    # Primero queda pendiente; después el admin decide cerrarla igual.
    with pytest.raises(HTTPException):
        await packing_service.complete(tenant_id, tid, admin)
    cerrada = await packing_service.complete(tenant_id, tid, admin, force_close=True)

    assert cerrada["status"] == PackingTaskStatus.COMPLETED_WITH_DIFFERENCES.value
    assert cerrada["approved_by"] == admin.id
    pedido = await order_service.get_order(tenant_id, oid)
    assert pedido["status"] == "ready_to_dispatch"


async def test_operario_no_puede_cerrar_con_faltantes():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    _, tid = await _packing_con_faltante(tenant_id, admin, "9602")
    operario = make_user({"_id": "packer-1", "tenant_id": tenant_id, "role": "packer"})
    # Asignada a él, para que el 403 sea por el cierre forzado y no por operar una tarea ajena.
    await tenant_db(tenant_id)[Collections.PACKING_TASKS].update_one(
        {"_id": to_object_id(tid)}, {"$set": {"assigned_to": operario.id}}
    )

    with pytest.raises(HTTPException) as exc:
        await packing_service.complete(tenant_id, tid, operario, force_close=True)
    assert exc.value.status_code == 403

    tarea = await packing_service.get_task(tenant_id, tid, admin)
    assert tarea["status"] == PackingTaskStatus.IN_PROGRESS.value


async def test_sin_faltantes_cierra_normal_sin_forzar():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [2], number="9603")
    bc = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    pick = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    await picking_service.scan(tenant_id, pick["id"], admin, bc, 2, None)
    await picking_service.complete(tenant_id, pick["id"], admin)
    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    pkg = (await packing_service.create_package(tenant_id, pk["id"], admin, None))["package_id"]
    await packing_service.scan(tenant_id, pk["id"], admin, bc, 2, pkg)

    cerrada = await packing_service.complete(tenant_id, pk["id"], admin)
    assert cerrada["status"] == PackingTaskStatus.COMPLETED.value
