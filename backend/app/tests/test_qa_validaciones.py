"""Validaciones de la QA funcional del 2026-09-29 (hallazgos de prioridad ALTA).

Cada caso prueba por el BORDE REAL: los límites de forma se prueban contra el esquema de
Pydantic (que es lo que ve la ruta) y las reglas de negocio contra el servicio. Probar solo
el servicio ya dio un falso positivo antes: el motivo vacío "pasaba" porque el test se
saltaba el esquema que lo bloquea.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.schemas.dispatch import DispatchLineInput
from app.schemas.inventory import AdjustmentRequest, ReceptionRequest, TransferRequest
from app.schemas.order import OrderLineInput
from app.seed import DEMO_ADMIN_EMAIL, run_seed
from app.services import dispatch_service, inventory_service

from .conftest import crear_referencias, make_user
from .test_split_dispatch import _drive_to_ready

# Sin ``pytestmark``: el modo asyncio es "auto" (``pytest.ini``) y marcar el módulo entero
# avisaría por cada prueba de esquema, que es síncrona.


def _campos(exc: ValidationError) -> set:
    return {e["loc"][0] for e in exc.errors()}


# ---------------------------------------------------------------------------
# A4 / A5 / M1: forma de la petición (Pydantic)
# ---------------------------------------------------------------------------
def _ajuste(**extra):
    base = {"product_id": "p", "warehouse_id": "w", "location_id": "l",
            "quantity": 1, "reason": "conteo"}
    return {**base, **extra}


def test_ajuste_rechaza_motivo_en_blanco_cantidad_cero_y_decimales():
    for payload, campo in (
        (_ajuste(reason="   "), "reason"),
        (_ajuste(reason=""), "reason"),
        (_ajuste(quantity=0), "quantity"),
        (_ajuste(quantity=1.5), "quantity"),
    ):
        with pytest.raises(ValidationError) as exc:
            AdjustmentRequest(**payload)
        assert campo in _campos(exc.value)


def test_ajuste_acepta_negativo_y_recorta_el_motivo():
    # Un ajuste de salida es legítimo; lo que no puede es dejar el saldo bajo cero (abajo).
    req = AdjustmentRequest(**_ajuste(quantity=-2, reason="  merma  "))
    assert req.quantity == -2 and req.reason == "merma"


def test_recepcion_rechaza_decimales_cero_y_negativos():
    base = {"product_id": "p", "warehouse_id": "w", "location_id": "l"}
    for cantidad in (1.5, 0, -5):
        with pytest.raises(ValidationError):
            ReceptionRequest(**base, quantity=cantidad)
    assert ReceptionRequest(**base, quantity=3).quantity == 3


def test_transferencia_rechaza_decimales_cero_y_negativos():
    base = {"product_id": "p", "warehouse_id": "w",
            "from_location_id": "a", "to_location_id": "b"}
    for cantidad in (2.5, 0, -1):
        with pytest.raises(ValidationError):
            TransferRequest(**base, quantity=cantidad)


def test_linea_de_pedido_exige_entero_positivo():
    for cantidad in (1.5, 0, -5):
        with pytest.raises(ValidationError):
            OrderLineInput(sku="S", ordered_quantity=cantidad)
    assert OrderLineInput(sku="S", ordered_quantity=2).ordered_quantity == 2


def test_linea_de_despacho_rechaza_negativos_pero_admite_cero():
    # 0 = "esta línea no va en esta guía"; negativo no significa nada.
    with pytest.raises(ValidationError):
        DispatchLineInput(sku="S", quantity=-1)
    assert DispatchLineInput(sku="S", quantity=0).quantity == 0


# ---------------------------------------------------------------------------
# A3: producto / bodega / ubicación tienen que existir y calzar
# ---------------------------------------------------------------------------
INEXISTENTE = "000000000000000000000000"


async def test_recepcion_con_producto_inexistente_no_crea_saldo_ni_movimiento():
    """El caso que ensució DEV: 200 y un movimiento colgado de un producto que no existe."""
    tid = "tA"
    refs = await crear_referencias(tid)
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(
            tenant_id=tid, product_id=INEXISTENTE, warehouse_id=refs["warehouse_id"],
            location_id=refs["A-01"], quantity=3, created_by="u1", sync_erp=False,
        )
    assert exc.value.status_code == 404
    db = tenant_db(tid)
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 0
    assert await db[Collections.INVENTORY_BALANCES].count_documents({}) == 0


async def test_movimientos_rechazan_bodega_y_ubicacion_inexistentes():
    tid = "tA"
    refs = await crear_referencias(tid)
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(
            tenant_id=tid, product_id=refs["product_id"], warehouse_id=INEXISTENTE,
            location_id=refs["A-01"], quantity=1, created_by="u1", sync_erp=False,
        )
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(
            tenant_id=tid, product_id=refs["product_id"], warehouse_id=refs["warehouse_id"],
            location_id=INEXISTENTE, quantity=1, created_by="u1", sync_erp=False,
        )
    assert exc.value.status_code == 404


async def test_ubicacion_de_otra_bodega_se_rechaza():
    """Sin esto se movía stock entre bodegas por la puerta de atrás."""
    tid = "tA"
    a = await crear_referencias(tid, sku="S-A", warehouse_code="BOD-A")
    b = await crear_referencias(tid, sku="S-B", warehouse_code="BOD-B")
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(
            tenant_id=tid, product_id=a["product_id"], warehouse_id=a["warehouse_id"],
            location_id=b["A-01"], quantity=1, created_by="u1", sync_erp=False,
        )
    assert exc.value.status_code == 409


async def test_producto_desactivado_se_rechaza():
    tid = "tA"
    refs = await crear_referencias(tid)
    await get_database()[Collections.PRODUCTS].update_one(
        {"tenant_id": tid}, {"$set": {"is_active": False}}
    )
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(
            tenant_id=tid, product_id=refs["product_id"], warehouse_id=refs["warehouse_id"],
            location_id=refs["A-01"], quantity=1, created_by="u1", sync_erp=False,
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# A5: vencimiento ya pasado
# ---------------------------------------------------------------------------
async def test_recepcion_rechaza_vencimiento_pasado_salvo_confirmacion_explicita():
    tid = "tA"
    refs = await crear_referencias(tid)
    vencido = now_utc() - timedelta(days=1916)
    comun = dict(tenant_id=tid, product_id=refs["product_id"],
                 warehouse_id=refs["warehouse_id"], location_id=refs["A-01"],
                 quantity=2, created_by="u1", lot_number="L1",
                 expiration_date=vencido, sync_erp=False)
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_reception(**comun)
    assert exc.value.status_code == 422

    # Confirmado por el operario (devolución que entra vencida): pasa.
    resultado = await inventory_service.create_reception(**comun, allow_expired=True)
    assert resultado["balance"]["quantity_on_hand"] == 2


# ---------------------------------------------------------------------------
# A4 / M1: el saldo no puede quedar negativo
# ---------------------------------------------------------------------------
async def test_ajuste_no_puede_dejar_el_saldo_negativo():
    tid = "tA"
    refs = await crear_referencias(tid)
    comun = dict(tenant_id=tid, product_id=refs["product_id"],
                 warehouse_id=refs["warehouse_id"], location_id=refs["A-01"],
                 created_by="u1")
    await inventory_service.create_reception(**comun, quantity=4, sync_erp=False)
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_adjustment(**comun, quantity=-999, reason="merma")
    assert exc.value.status_code == 409
    saldo = await tenant_db(tid)[Collections.INVENTORY_BALANCES].find_one({})
    assert saldo["quantity_on_hand"] == 4  # intacto


async def test_transferencia_mayor_al_saldo_y_origen_igual_a_destino_se_rechazan():
    tid = "tA"
    refs = await crear_referencias(tid, locations=("A-01", "A-02"))
    comun = dict(tenant_id=tid, product_id=refs["product_id"],
                 warehouse_id=refs["warehouse_id"], created_by="u1")
    await inventory_service.create_reception(
        **comun, location_id=refs["A-01"], quantity=4, sync_erp=False
    )
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_transfer(
            **comun, from_location_id=refs["A-01"], to_location_id=refs["A-02"], quantity=999
        )
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await inventory_service.create_transfer(
            **comun, from_location_id=refs["A-01"], to_location_id=refs["A-01"], quantity=1
        )
    assert exc.value.status_code == 400
    saldo = await tenant_db(tid)[Collections.INVENTORY_BALANCES].find_one(
        {"location_id": refs["A-01"]}
    )
    assert saldo["quantity_on_hand"] == 4


# ---------------------------------------------------------------------------
# A1 / A2: despacho
# ---------------------------------------------------------------------------
async def _admin():
    return make_user(await get_database()[Collections.USERS].find_one({"email": DEMO_ADMIN_EMAIL}))


async def test_despacho_con_la_misma_clave_de_idempotencia_no_emite_dos_guias():
    """Con el envío al ERP encendido, un doble clic costaba DOS folios de Defontana."""
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, _sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])

    primero = await dispatch_service.confirm_dispatch(
        tenant_id, oid, admin, guide_number="G-1",
        lines=[{"sku": sku0, "quantity": 5}], idempotency_key="clave-1",
    )
    segundo = await dispatch_service.confirm_dispatch(
        tenant_id, oid, admin, guide_number="G-1",
        lines=[{"sku": sku0, "quantity": 5}], idempotency_key="clave-1",
    )
    assert primero["id"] == segundo["id"]
    assert await tenant_db(tenant_id)[Collections.DISPATCHES].count_documents({}) == 1


async def test_despacho_rechaza_sku_ajeno_y_no_filtra_lineas_en_silencio():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, _sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])

    with pytest.raises(HTTPException) as exc:
        await dispatch_service.confirm_dispatch(
            tenant_id, oid, admin, lines=[{"sku": "NO-EXISTE", "quantity": 1}]
        )
    assert exc.value.status_code == 404
    assert await tenant_db(tenant_id)[Collections.DISPATCHES].count_documents({}) == 0


async def test_despacho_no_puede_superar_lo_empacado():
    tenant_id = (await run_seed())["tenant_id"]
    admin = await _admin()
    oid, (sku0, _sku1) = await _drive_to_ready(tenant_id, admin, [5, 3])

    with pytest.raises(HTTPException) as exc:
        await dispatch_service.confirm_dispatch(
            tenant_id, oid, admin, lines=[{"sku": sku0, "quantity": 99}]
        )
    assert exc.value.status_code == 409
    assert await tenant_db(tenant_id)[Collections.DISPATCHES].count_documents({}) == 0


# ---------------------------------------------------------------------------
# Limpieza (punto 0 del handoff): el script tiene que ser idempotente y no tocar lo sano
# ---------------------------------------------------------------------------
async def test_limpieza_borra_solo_lo_huerfano_y_es_idempotente(capsys):
    from app.maintenance.limpiar_movimientos_huerfanos import limpiar

    tid = "tA"
    refs = await crear_referencias(tid)
    await inventory_service.create_reception(
        tenant_id=tid, product_id=refs["product_id"], warehouse_id=refs["warehouse_id"],
        location_id=refs["A-01"], quantity=3, created_by="u1", sync_erp=False,
    )
    db = get_database()
    # Los 8 movimientos de DEV: producto inexistente, sin saldo ni SKU que los explique.
    for _ in range(2):
        await db[Collections.INVENTORY_MOVEMENTS].insert_one(
            {"tenant_id": tid, "product_id": INEXISTENTE, "movement_type": "receipt",
             "quantity": 1.5, "warehouse_id": refs["warehouse_id"]}
        )
    await db[Collections.INVENTORY_BALANCES].insert_one(
        {"tenant_id": tid, "product_id": INEXISTENTE, "warehouse_id": refs["warehouse_id"],
         "location_id": refs["A-01"], "quantity_on_hand": 2}
    )

    # Dry-run: reporta y no borra.
    await limpiar(apply=False)
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 3

    await limpiar(apply=True)
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 1  # la recepción sana
    assert await db[Collections.INVENTORY_BALANCES].count_documents({}) == 1

    # Idempotente: correrlo de nuevo no rompe ni borra de más.
    await limpiar(apply=True)
    assert await db[Collections.INVENTORY_MOVEMENTS].count_documents({}) == 1
    assert "Nada que limpiar" in capsys.readouterr().out
