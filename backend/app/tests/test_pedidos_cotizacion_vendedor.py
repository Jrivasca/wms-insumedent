"""Fecha, cotización y vendedor del pedido (pedido del dueño, 2026-10-05)."""
import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.integrations.defontana.mapper import DefontanaMapper
from app.models import Collections
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import order_service, picking_service

from .conftest import make_user
from .test_split_dispatch import _make_order

pytestmark = pytest.mark.asyncio

# Forma real de Order/Get (pedido 2815 de QA, 2026-10-05).
RAW = {"number": 2815, "creationDate": "2026-07-07T00:00:00", "sellerID": "11678885-3",
       "referenceNumberPricingID": "7942", "comment": " 525800-248-COT26 \n", "details": []}


def test_mapper_saca_cotizacion_vendedor_y_comentario():
    assert DefontanaMapper.order_extra_fields(RAW) == {
        "quotation_number": "7942", "seller_code": "11678885-3", "observations": "525800-248-COT26"}
    vacio = DefontanaMapper.order_extra_fields({"referenceNumberPricingID": "", "sellerID": None})
    assert vacio == {"quotation_number": None, "seller_code": None, "observations": None}


async def test_pedidos_sincronizados_antes_los_derivan_del_dato_crudo():
    t = "t-cot"
    await tenant_db(t)[Collections.ORDERS].insert_one(
        {"tenant_id": t, "erp_order_number": "2815", "status": "imported", "lines": [],
         "created_at": now_utc(), "raw_erp_data": {"order": RAW}})
    o = (await order_service.list_orders(t, user_id="ana"))["items"][0]
    assert o["quotation_number"] == "7942" and o["seller_code"] == "11678885-3"


async def test_la_tarea_de_picking_trae_el_resumen_del_pedido():
    tenant_id = (await run_seed())["tenant_id"]
    admin = make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))
    order = await _make_order(tenant_id, [1], number="9800")
    await tenant_db(tenant_id)[Collections.ORDERS].update_one(
        {"erp_order_number": "9800"},
        {"$set": {"quotation_number": "8060", "seller_code": "VENDEDOR"}})
    task = await order_service.create_picking_task(tenant_id, order["id"], admin.id)
    detalle = await picking_service.get_task(tenant_id, task["id"], admin)
    assert detalle["order_info"]["quotation_number"] == "8060"
    assert detalle["order_info"]["seller_code"] == "VENDEDOR"
