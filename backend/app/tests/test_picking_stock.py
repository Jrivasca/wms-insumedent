"""Picking contra el stock real: lo escaneado queda tomado y no se escanea de más.

Observaciones del dueño en DEV (2026-10-02): sin stock no debería dejar pickear (pero el
pedido tiene que poder avanzar), ni aceptar más de lo que hay; lo pickeado debe quedar
tomado para que otro pedido en paralelo no lo escanee; y un pedido sin stock suficiente
debe generar una alerta de quiebre.
"""
import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import order_service, picking_service

from .conftest import make_user
from .test_split_dispatch import _barcode_for, _make_order

pytestmark = pytest.mark.asyncio


async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def _deja_stock(tenant_id: str, product_id: str, por_ubicacion: dict) -> dict:
    """Deja el producto SOLO con el stock indicado ({código: cantidad}), sin lote.

    Crea las ubicaciones que falten en la bodega del producto. Devuelve {código: id}.
    """
    db = tenant_db(tenant_id)
    bal = await db[Collections.INVENTORY_BALANCES].find_one({"product_id": product_id})
    warehouse_id = bal["warehouse_id"]
    await db[Collections.INVENTORY_BALANCES].delete_many({"product_id": product_id})
    ids = {}
    for code, qty in por_ubicacion.items():
        loc = await db[Collections.LOCATIONS].find_one({"warehouse_id": warehouse_id, "code": code})
        if not loc:
            res = await db[Collections.LOCATIONS].insert_one(
                {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "code": code,
                 "type": "storage", "is_active": True}
            )
            loc_id = str(res.inserted_id)
        else:
            loc_id = str(loc["_id"])
        ids[code] = loc_id
        await db[Collections.INVENTORY_BALANCES].insert_one(
            {"tenant_id": tenant_id, "product_id": product_id, "warehouse_id": warehouse_id,
             "location_id": loc_id, "lot_number": None, "expiration_date": None,
             "quantity_on_hand": qty, "quantity_reserved": 0, "quantity_blocked": 0}
        )
    return ids


async def _pedido(tenant_id, admin, qty, number):
    order = await _make_order(tenant_id, [qty], number=number)
    pid = order["lines"][0]["product_id"]
    return order, pid, await _barcode_for(tenant_id, pid)


async def test_no_escanea_mas_de_lo_que_hay():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order, pid, bc = await _pedido(tenant_id, admin, 5, "9700")
    await _deja_stock(tenant_id, pid, {"T-01": 3})
    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)

    r = await picking_service.scan(tenant_id, task["id"], admin, bc, 4, None)
    assert r["status"] == "rejected" and "solo quedan 3" in r["message"]
    assert (await picking_service.scan(tenant_id, task["id"], admin, bc, 3, None))["status"] == "ok"
    r = await picking_service.scan(tenant_id, task["id"], admin, bc, 1, None)
    assert r["status"] == "rejected" and "No hay stock disponible" in r["message"]
    assert "parcial" in r["message"]

    # Sin stock, el pedido avanza con el cierre parcial y nada queda negativo.
    await picking_service.complete(tenant_id, task["id"], admin, allow_partial=True)
    saldos = [b async for b in tenant_db(tenant_id)[Collections.INVENTORY_BALANCES].find(
        {"product_id": pid})]
    assert all((b.get("quantity_on_hand") or 0) >= 0 for b in saldos)
    pedido = await order_service.get_order(tenant_id, order["id"])
    assert pedido["status"] == "picked"


async def test_dos_pedidos_no_toman_las_mismas_unidades():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    o1, pid, bc = await _pedido(tenant_id, admin, 4, "9701")
    o2 = await _make_order(tenant_id, [4], number="9702")
    await _deja_stock(tenant_id, pid, {"T-01": 5})
    t1 = await order_service.create_picking_task(tenant_id, o1["id"], admin.id)
    t2 = await order_service.create_picking_task(tenant_id, o2["id"], admin.id)

    assert (await picking_service.scan(tenant_id, t1["id"], admin, bc, 4, None))["status"] == "ok"
    # Quedó 1 libre: el segundo pedido no puede tomar 2.
    r = await picking_service.scan(tenant_id, t2["id"], admin, bc, 2, None)
    assert r["status"] == "rejected" and "solo quedan 1" in r["message"]
    assert (await picking_service.scan(tenant_id, t2["id"], admin, bc, 1, None))["status"] == "ok"

    # Reiniciar la línea del primero libera sus unidades.
    sku = t1["lines"][0]["sku"]
    await picking_service.reset_line(tenant_id, t1["id"], admin, sku)
    assert (await picking_service.scan(tenant_id, t2["id"], admin, bc, 3, None))["status"] == "ok"


async def test_sin_stock_en_la_sugerida_la_cambia_a_otra_ubicacion():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order, pid, bc = await _pedido(tenant_id, admin, 2, "9703")
    ids = await _deja_stock(tenant_id, pid, {"T-01": 0, "T-02": 6})
    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    db = tenant_db(tenant_id)
    # Se fuerza la sugerida a la vacía, como si el stock se hubiera movido después.
    await db[Collections.PICKING_TASKS].update_one(
        {"_id": __import__("bson").ObjectId(task["id"])},
        {"$set": {"lines.0.suggested_location_id": ids["T-01"]}},
    )

    r = await picking_service.scan(tenant_id, task["id"], admin, bc, 2, None)
    assert r["status"] == "rejected" and "cambió a T-02" in r["message"]
    assert (await picking_service.scan(tenant_id, task["id"], admin, bc, 2, None))["status"] == "ok"


async def test_alerta_de_quiebre_al_generar_y_al_cerrar_incompleto():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order, pid, bc = await _pedido(tenant_id, admin, 5, "9704")
    await _deja_stock(tenant_id, pid, {"T-01": 2})
    db = tenant_db(tenant_id)

    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    alertas = [n async for n in db[Collections.NOTIFICATIONS].find({"type": "stock_shortage"})]
    assert any(n["title"] == "Quiebre de stock: pedido 9704" for n in alertas)
    assert any("pide 5, libre 2" in n["body"] for n in alertas)

    await picking_service.scan(tenant_id, task["id"], admin, bc, 2, None)
    await picking_service.complete(tenant_id, task["id"], admin, allow_partial=True)
    alertas = [n async for n in db[Collections.NOTIFICATIONS].find({"type": "stock_shortage"})]
    assert any(n["title"] == "Pedido 9704 quedó incompleto" and "faltan 3 de 5" in n["body"]
               for n in alertas)


async def test_sin_quiebre_no_hay_alerta():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order, pid, bc = await _pedido(tenant_id, admin, 2, "9705")
    await _deja_stock(tenant_id, pid, {"T-01": 10})
    await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    db = tenant_db(tenant_id)
    assert await db[Collections.NOTIFICATIONS].count_documents({"type": "stock_shortage"}) == 0


async def test_stock_sin_ubicar_se_menciona():
    """Antes del corte casi todo está en recepción: «no hay stock» a secas confundía."""
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    order, pid, bc = await _pedido(tenant_id, admin, 2, "9706")
    await _deja_stock(tenant_id, pid, {"T-01": 0})
    db = tenant_db(tenant_id)
    bal = await db[Collections.INVENTORY_BALANCES].find_one({"product_id": pid})
    rec = await db[Collections.LOCATIONS].insert_one(
        {"tenant_id": tenant_id, "warehouse_id": bal["warehouse_id"], "code": "REC-T",
         "type": "receiving", "is_active": True}
    )
    await db[Collections.INVENTORY_BALANCES].insert_one(
        {"tenant_id": tenant_id, "product_id": pid, "warehouse_id": bal["warehouse_id"],
         "location_id": str(rec.inserted_id), "lot_number": None, "quantity_on_hand": 7,
         "quantity_reserved": 0, "quantity_blocked": 0}
    )
    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    r = await picking_service.scan(tenant_id, task["id"], admin, bc, 1, None)
    assert r["status"] == "rejected" and "Hay 7 en recepción sin ubicar" in r["message"]
