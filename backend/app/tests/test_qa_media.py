"""Hallazgos de prioridad MEDIA de la QA funcional del 2026-09-29."""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.models.packing import PackingTaskStatus
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import (
    inventory_service,
    order_service,
    packing_service,
    picking_service,
    product_service,
)

from .conftest import make_user
from .test_split_dispatch import _barcode_for, _drive_to_ready, _make_order

pytestmark = pytest.mark.asyncio


async def crear_referencias(tenant_id: str, *, locations=("A-01",)) -> dict:
    """Producto, bodega y ubicaciones reales, con sus ids.

    Local a propósito y no en ``conftest``: la tanda ALTA agrega ahí un helper igual, y
    estas dos ramas salen las dos de ``main`` sin apilarse. Al mergear ambas, este archivo
    puede pasar a usar el de ``conftest``.
    """
    db = get_database()
    producto = await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": tenant_id, "sku": "SKU1", "name": "Prod", "is_active": True}
    )
    bodega = await db[Collections.WAREHOUSES].insert_one(
        {"tenant_id": tenant_id, "code": "BOD1", "name": "BOD1", "is_active": True}
    )
    refs = {"product_id": str(producto.inserted_id), "warehouse_id": str(bodega.inserted_id)}
    for code in locations:
        loc = await db[Collections.LOCATIONS].insert_one(
            {"tenant_id": tenant_id, "warehouse_id": refs["warehouse_id"], "code": code,
             "type": "storage", "is_active": True}
        )
        refs[code] = str(loc.inserted_id)
    return refs


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


# ---------------------------------------------------------------------------
# M5: ORIGEN → DESTINO mostraba ObjectIds
# ---------------------------------------------------------------------------
async def test_los_movimientos_traen_el_codigo_de_ubicacion():
    tid = "tA"
    refs = await crear_referencias(tid, locations=("A-01", "A-02"))
    comun = dict(tenant_id=tid, product_id=refs["product_id"],
                 warehouse_id=refs["warehouse_id"], created_by="u1")
    await inventory_service.create_reception(
        **comun, location_id=refs["A-01"], quantity=5, sync_erp=False
    )
    await inventory_service.create_transfer(
        **comun, from_location_id=refs["A-01"], to_location_id=refs["A-02"], quantity=2
    )
    user = make_user({"_id": "u1", "tenant_id": tid, "role": "admin"})
    movimientos = (await inventory_service.list_movements(tid, user=user))["items"]
    transferencia = next(m for m in movimientos if m["movement_type"] == "transfer")
    assert transferencia["from_location_code"] == "A-01"
    assert transferencia["to_location_code"] == "A-02"
    recepcion = next(m for m in movimientos if m["movement_type"] == "receipt")
    assert recepcion["to_location_code"] == "A-01" and recepcion["from_location_code"] is None


# ---------------------------------------------------------------------------
# M2: una tarea de packing cerrada no se sigue editando
# ---------------------------------------------------------------------------
async def test_packing_cerrado_no_acepta_bultos_nuevos_ni_escaneos():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    await _drive_to_ready(tenant_id, admin, [5, 3])
    tarea = (await packing_service.list_tasks(tenant_id, admin))["items"][0]

    # La tarea quedó cerrada; agregarle un bulto la dejaba "Completado" y editable a la vez.
    with pytest.raises(HTTPException) as exc:
        await packing_service.create_package(tenant_id, tarea["id"], admin, None)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await packing_service.reset_line(tenant_id, tarea["id"], admin, tarea["lines"][0]["sku"])
    assert exc.value.status_code == 409


async def test_packing_con_diferencias_queda_en_su_propio_estado():
    """Antes quedaba como «Completado» a secas: la diferencia no se veía en la lista."""
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [5, 3], number="9200")
    oid = order["id"]
    bcs = [await _barcode_for(tenant_id, ln["product_id"]) for ln in order["lines"]]
    pick = await order_service.create_picking_task(tenant_id, oid, admin.id)
    for bc, q in zip(bcs, [5, 3]):
        await picking_service.scan(tenant_id, pick["id"], admin, bc, q, None)
    await picking_service.complete(tenant_id, pick["id"], admin)

    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    pkg = (await packing_service.create_package(tenant_id, pk["id"], admin, None))["package_id"]
    # Se empaca una unidad menos de la primera línea.
    for bc, q in zip(bcs, [4, 3]):
        await packing_service.scan(tenant_id, pk["id"], admin, bc, q, pkg)
    cerrada = await packing_service.complete(tenant_id, pk["id"], admin, force_close=True)

    assert cerrada["status"] == PackingTaskStatus.COMPLETED_WITH_DIFFERENCES.value
    # Y sigue contando como empacada para el pedido (si no, no se podría despachar).
    pedido = await order_service.get_order(tenant_id, oid)
    assert sum(l["packed_quantity"] for l in pedido["lines"]) == 7
    assert pedido["status"] == "ready_to_dispatch"


# ---------------------------------------------------------------------------
# M7: Pedidos y Picking decían distinto sobre el mismo pedido
# ---------------------------------------------------------------------------
async def test_pedidos_muestra_el_avance_de_la_tarea_en_curso():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [20, 3], number="9300")
    oid = order["id"]
    bc = await _barcode_for(tenant_id, order["lines"][0]["product_id"])
    tarea = await order_service.create_picking_task(tenant_id, oid, admin.id)
    await picking_service.scan(tenant_id, tarea["id"], admin, bc, 1, None)

    detalle = await order_service.get_order(tenant_id, oid)
    linea = detalle["lines"][0]
    # Lo confirmado sigue en 0 (la tarea no se ha cerrado) pero el avance en curso se ve.
    assert linea["picked_quantity"] == 0
    assert linea["picked_quantity_live"] == 1

    listado = await order_service.list_orders(tenant_id)
    en_lista = next(o for o in listado["items"] if o["id"] == oid)
    assert en_lista["lines"][0]["picked_quantity_live"] == 1


# ---------------------------------------------------------------------------
# M8: el SKU exacto no aparecía en el buscador
# ---------------------------------------------------------------------------
async def test_el_sku_exacto_aparece_aunque_el_limite_sea_chico():
    tid = "tA"
    db = get_database()
    # Muchos productos cuyo nombre ordena ANTES que el buscado, para llenar la página.
    for i in range(12):
        await db[Collections.PRODUCTS].insert_one(
            {"tenant_id": tid, "sku": f"OTRO{i:03d}", "name": f"AAA producto {i}",
             "is_active": True}
        )
    await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": tid, "sku": "ANES014", "name": "ZZZ anestesia", "is_active": True}
    )

    resultado = await product_service.list_products(tid, search="ANES014", limit=8)
    skus = [p["sku"] for p in resultado["items"]]
    assert skus[0] == "ANES014", skus


# ---------------------------------------------------------------------------
# M10: los lotes vencidos figuraban como disponibles y se podían pickear
# ---------------------------------------------------------------------------
async def test_un_lote_vencido_se_marca_y_no_se_puede_pickear():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [2, 1], number="9400")
    linea = order["lines"][0]
    bc = await _barcode_for(tenant_id, linea["product_id"])
    tarea = await order_service.create_picking_task(tenant_id, order["id"], admin.id)

    db = tenant_db(tenant_id)
    # El stock del seed pasa a tener un lote ya vencido.
    saldo = await db[Collections.INVENTORY_BALANCES].find_one(
        {"product_id": linea["product_id"], "quantity_on_hand": {"$gt": 0}}
    )
    await db[Collections.INVENTORY_BALANCES].update_one(
        {"_id": saldo["_id"]},
        {"$set": {"lot_number": "L-VENCIDO",
                  "expiration_date": now_utc() - timedelta(days=1916)}},
    )

    lotes = await inventory_service.available_lots(
        tenant_id, linea["product_id"], tarea["warehouse_id"]
    )
    vencido = next(l for l in lotes if l["lot_number"] == "L-VENCIDO")
    assert vencido["expired"] is True

    r = await picking_service.scan(
        tenant_id, tarea["id"], admin, bc, 1, saldo["location_id"], lot_number="L-VENCIDO"
    )
    assert r["status"] == "rejected" and "vencido" in r["message"].lower()


# ---------------------------------------------------------------------------
# M6: el movimiento de packing tiene que mover exactamente lo que hay en los bultos
# ---------------------------------------------------------------------------
async def test_el_movimiento_de_packing_coincide_con_lo_que_hay_en_los_bultos():
    """En DEV se vieron 4 unidades en PACKING con 3 empacadas. Con los escaneos huérfanos ya
    corregidos y la tarea cerrada bloqueada, las dos cifras no se pueden separar."""
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order = await _make_order(tenant_id, [4, 2], number="9500")
    bcs = [await _barcode_for(tenant_id, ln["product_id"]) for ln in order["lines"]]
    pick = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    for bc, q in zip(bcs, [4, 2]):
        await picking_service.scan(tenant_id, pick["id"], admin, bc, q, None)
    await picking_service.complete(tenant_id, pick["id"], admin)

    pk = (await packing_service.list_tasks(tenant_id, admin))["items"][0]
    await packing_service.start_task(tenant_id, pk["id"], admin)
    pkg = (await packing_service.create_package(tenant_id, pk["id"], admin, None))["package_id"]
    for bc, q in zip(bcs, [3, 2]):  # una unidad menos en la primera línea
        await packing_service.scan(tenant_id, pk["id"], admin, bc, q, pkg)
    await packing_service.complete(tenant_id, pk["id"], admin, force_close=True)

    db = tenant_db(tenant_id)
    tarea = await db[Collections.PACKING_TASKS].find_one({"_id": to_object_id(pk["id"])})
    en_bultos = {}
    for p in tarea.get("packages", []):
        for it in p.get("items", []):
            en_bultos[it["sku"]] = en_bultos.get(it["sku"], 0) + it["quantity"]

    movidos = {}
    async for m in db[Collections.INVENTORY_MOVEMENTS].find(
        {"movement_type": "pack", "reference_id": pk["id"]}
    ):
        linea = next(l for l in tarea["lines"] if l["product_id"] == m["product_id"])
        movidos[linea["sku"]] = movidos.get(linea["sku"], 0) + m["quantity"]

    assert movidos == en_bultos, f"movidos={movidos} en_bultos={en_bultos}"
