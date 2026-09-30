"""Limpieza de movimientos y saldos colgados de un producto que no existe.

Durante la QA funcional del 2026-09-29 se crearon en DEV 8 movimientos con un
``product_id`` inexistente (``000000000000000000000000``): 3 recepciones, 2 transferencias
y 3 ajustes. El backend los aceptaba porque no validaba la referencia; ahora sí
(``inventory_service.assert_references_exist``), así que esto es solo la secuela.

El stock que dejaron es invisible en Inventario (la pantalla muestra por SKU) e imposible
de pickear o conciliar: hay que borrarlo, no ajustarlo.

Es idempotente y **por defecto solo reporta** (dry-run). Se corre a mano:

    docker compose exec -T backend python -m app.maintenance.limpiar_movimientos_huerfanos
    docker compose exec -T backend python -m app.maintenance.limpiar_movimientos_huerfanos --apply

Contra el droplet, el respaldo va ANTES (ver DEPLOY.md / CLAUDE.md), y el dry-run se lee
entero antes de aplicar: borra documentos y no tiene vuelta atrás.

Usa ``get_database()`` a propósito (mantenimiento cross-tenant, como ``seed.py``).
"""
import asyncio
import sys

from app.core.database import get_database
from app.core.utils import to_object_id
from app.models import Collections


async def _productos_existentes(db) -> set:
    """Ids de producto (como texto) que sí existen, para no consultar uno por uno."""
    return {
        str(doc["_id"])
        async for doc in db[Collections.PRODUCTS].find({}, {"_id": 1})
    }


async def limpiar(apply: bool) -> None:
    db = get_database()
    existentes = await _productos_existentes(db)

    movimientos_huerfanos = []
    async for mov in db[Collections.INVENTORY_MOVEMENTS].find({}):
        pid = mov.get("product_id")
        # Un ``product_id`` vacío o con formato inválido también cuenta: tampoco resuelve
        # a un producto real.
        if pid is None or to_object_id(pid) is None or str(pid) not in existentes:
            movimientos_huerfanos.append(mov)

    saldos_huerfanos = []
    async for bal in db[Collections.INVENTORY_BALANCES].find({}):
        pid = bal.get("product_id")
        if pid is None or to_object_id(pid) is None or str(pid) not in existentes:
            saldos_huerfanos.append(bal)

    if not movimientos_huerfanos and not saldos_huerfanos:
        print("Nada que limpiar: no hay movimientos ni saldos de productos inexistentes.")
        return

    print(f"Movimientos colgados de un producto inexistente: {len(movimientos_huerfanos)}")
    for mov in movimientos_huerfanos:
        print(
            f"  {mov.get('created_at')} tenant {mov.get('tenant_id')} "
            f"{mov.get('movement_type')} product_id={mov.get('product_id')} "
            f"cantidad={mov.get('quantity')} "
            f"origen={mov.get('from_location_id')} destino={mov.get('to_location_id')} "
            f"motivo={mov.get('reason')!r}"
        )

    print(f"Saldos colgados de un producto inexistente: {len(saldos_huerfanos)}")
    for bal in saldos_huerfanos:
        print(
            f"  tenant {bal.get('tenant_id')} product_id={bal.get('product_id')} "
            f"bodega={bal.get('warehouse_id')} ubicación={bal.get('location_id')} "
            f"en mano={bal.get('quantity_on_hand')}"
        )

    if not apply:
        print("DRY-RUN: no se borró nada. Repita con --apply para aplicar.")
        return

    borrados_mov = 0
    for mov in movimientos_huerfanos:
        r = await db[Collections.INVENTORY_MOVEMENTS].delete_one({"_id": mov["_id"]})
        borrados_mov += r.deleted_count
    borrados_bal = 0
    for bal in saldos_huerfanos:
        r = await db[Collections.INVENTORY_BALANCES].delete_one({"_id": bal["_id"]})
        borrados_bal += r.deleted_count

    print(f"APLICADO: {borrados_mov} movimiento(s) y {borrados_bal} saldo(s) borrados.")


if __name__ == "__main__":
    asyncio.run(limpiar(apply="--apply" in sys.argv))
