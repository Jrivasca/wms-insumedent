"""Pedidos "no leídos" por usuario, como el correo (pedido del dueño, 2026-10-05)."""
from types import SimpleNamespace

import pytest

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.services import order_service

pytestmark = pytest.mark.asyncio

T = "t-noleidos"


async def _pedido_sincronizado(numero: str) -> str:
    """Como lo deja la sincronización con Defontana: sin ``seen_by``."""
    res = await tenant_db(T)[Collections.ORDERS].insert_one(
        {"tenant_id": T, "erp_order_number": numero, "status": "imported", "lines": [],
         "created_at": now_utc(), "created_by": "sistema"}
    )
    return str(res.inserted_id)


def _unread(listado, numero):
    return next(o["unread"] for o in listado["items"] if o["erp_order_number"] == numero)


async def test_es_no_leido_hasta_que_cada_usuario_lo_abre():
    oid = await _pedido_sincronizado("5001")
    await _pedido_sincronizado("5002")

    a = await order_service.list_orders(T, user_id="ana")
    assert _unread(a, "5001") and a["unread_total"] == 2
    assert all("seen_by" not in o for o in a["items"])  # los ids de usuarios no salen

    abierto = await order_service.get_order(T, oid, seen_by_user="ana")
    assert abierto["unread"] is False

    a = await order_service.list_orders(T, user_id="ana")
    b = await order_service.list_orders(T, user_id="beto")
    assert not _unread(a, "5001") and a["unread_total"] == 1
    assert _unread(b, "5001") and b["unread_total"] == 2

    solo = await order_service.list_orders(T, user_id="ana", unread_only=True)
    assert [o["erp_order_number"] for o in solo["items"]] == ["5002"]


async def test_abrir_desde_un_servicio_no_marca():
    oid = await _pedido_sincronizado("5003")
    await order_service.get_order(T, oid)
    assert (await order_service.list_orders(T, user_id="ana"))["unread_total"] == 1


async def test_marcar_todos_como_leidos():
    await _pedido_sincronizado("5004")
    await _pedido_sincronizado("5005")
    assert (await order_service.mark_all_read(T, "ana"))["marked"] == 2
    assert (await order_service.list_orders(T, user_id="ana"))["unread_total"] == 0
    assert (await order_service.list_orders(T, user_id="beto"))["unread_total"] == 2


async def test_el_que_lo_crea_a_mano_no_lo_ve_como_nuevo():
    linea = SimpleNamespace(sku="X-1", name="X", unit="UN", ordered_quantity=1, product_id=None)
    await order_service.create_order_from_lines(
        tenant_id=T, erp_order_number="5006", customer="C", lines=[linea], created_by="ana"
    )
    assert not _unread(await order_service.list_orders(T, user_id="ana"), "5006")
    assert _unread(await order_service.list_orders(T, user_id="beto"), "5006")
