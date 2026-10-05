"""Reinicio de la etapa de pruebas contra el Defontana de QA (SOLO pruebas).

Defontana restaura su base de QA los fines de semana (copia de producción con ~1 semana de
desfase): los pedidos de la semana anterior cambian o desaparecen allá. Para que el WMS
"vuelva" junto con el ERP, el lunes se reinicia también acá.

El primer reinicio (cron del droplet, 2026-09-28) borraba pedidos y tareas pero **no tocaba
el inventario**: lo que las pruebas habían movido (bodega → staging → packing → despacho)
quedaba en STAGING/PACKING sin pedido que lo moviera, y con saldos negativos (el movimiento
de packing no lleva lote, así que un producto con lote dejaba +q en la fila con lote y −q en
la sin lote). Pasó el 2026-10-05: 19 u en STAGING, 7 en PACKING y 5 negativos.

Lo que hace este módulo es **revertir** esos movimientos con
``inventory_service.reverse_moves_for_reference`` (inverso auditable, mismo lote, marca el
original), que deja cada saldo exactamente como antes de la prueba. Dos modos:

- Por defecto: revierte solo los movimientos **huérfanos** (su tarea o despacho ya no
  existe). Seguro con pedidos en curso: no toca nada que tenga tarea viva.
- ``--reset-semanal``: revierte TODOS los movimientos de picking/packing/despacho, borra
  pedidos, tareas, despachos y envíos al ERP, y re-sincroniza los pedidos desde Defontana.
  Es lo que corre el cron de los lunes (``deploy/qa/wms-reset-pedidos-qa.sh``).

Por defecto solo muestra lo que haría (dry-run). Se corre en el contenedor del backend:

    python -m app.maintenance.reiniciar_qa --tenant <id>
    python -m app.maintenance.reiniciar_qa --tenant <id> --apply
    python -m app.maintenance.reiniciar_qa --tenant <id> --reset-semanal --apply

No toca productos, ubicaciones, recepciones, ajustes ni la conciliación. QUITAR el cron al
terminar la etapa de pruebas.
"""
import argparse
import asyncio
from typing import Any, Dict, List, Tuple

from app.core.tenant_db import tenant_db
from app.core.utils import to_object_id
from app.models import Collections
from app.models.inventory import MovementType
from app.services import inventory_service

# Referencia de cada movimiento operativo y la colección donde vive su dueño.
REFERENCIAS = {
    "dispatch": Collections.DISPATCHES,
    "packing_task": Collections.PACKING_TASKS,
    "picking_task": Collections.PICKING_TASKS,
}
TIPOS = [MovementType.PICK.value, MovementType.PACK.value, MovementType.DISPATCH.value]

# Lo que borra el reinicio semanal (todo lo que cuelga de los pedidos de la semana).
COLECCIONES_PEDIDOS = [
    Collections.ORDERS,
    Collections.PICKING_TASKS,
    Collections.PACKING_TASKS,
    Collections.DISPATCHES,
    Collections.SYNC_JOBS,
    Collections.REPLENISHMENT_ALERTS,
]


async def movimientos_a_revertir(tenant_id: str, solo_huerfanos: bool) -> List[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    movs = await db[Collections.INVENTORY_MOVEMENTS].find(
        {
            "reference_type": {"$in": list(REFERENCIAS)},
            "movement_type": {"$in": TIPOS},
            "reversed": {"$ne": True},
            "is_reversal": {"$ne": True},
        }
    ).to_list(length=100000)
    if not solo_huerfanos:
        return movs
    vivos: Dict[str, bool] = {}
    out = []
    for m in movs:
        ref = m.get("reference_id")
        clave = f"{m['reference_type']}:{ref}"
        if clave not in vivos:
            dueño = await db[REFERENCIAS[m["reference_type"]]].find_one(
                {"_id": to_object_id(ref)}, {"_id": 1}
            ) if to_object_id(ref) else None
            vivos[clave] = dueño is not None
        if not vivos[clave]:
            out.append(m)
    return out


def proyectar(movs: List[Dict[str, Any]]) -> Dict[Tuple[str, str, Any], float]:
    """Cambio que dejaría la reversa en cada saldo (ubicación, producto, lote)."""
    delta: Dict[Tuple[str, str, Any], float] = {}
    for m in movs:
        q = m.get("quantity") or 0
        lot = m.get("lot_number")
        if m.get("to_location_id"):
            k = (m["to_location_id"], m["product_id"], lot)
            delta[k] = delta.get(k, 0) - q
        if m.get("from_location_id"):
            k = (m["from_location_id"], m["product_id"], lot)
            delta[k] = delta.get(k, 0) + q
    return delta


async def revertir(tenant_id: str, movs: List[Dict[str, Any]]) -> int:
    referencias = sorted({(m["reference_type"], m["reference_id"]) for m in movs})
    total = 0
    for ref_type, ref_id in referencias:
        total += await inventory_service.reverse_moves_for_reference(
            tenant_id=tenant_id, reference_type=ref_type, reference_id=ref_id,
            created_by="reinicio-qa", reason="Reinicio de pruebas QA: vuelve al stock previo",
        )
    return total


async def _informe(tenant_id: str, movs: List[Dict[str, Any]]) -> None:
    db = tenant_db(tenant_id)
    print(f"Movimientos a revertir: {len(movs)} "
          f"({len({(m['reference_type'], m['reference_id']) for m in movs})} tareas/despachos)")
    delta = proyectar(movs)
    if not delta:
        return
    codes = {str(l["_id"]): (l.get("code"), l.get("type"))
             async for l in db[Collections.LOCATIONS].find({}, {"code": 1, "type": 1})}
    skus = {str(p["_id"]): p.get("sku")
            async for p in db[Collections.PRODUCTS].find({}, {"sku": 1})}
    print("Saldos que cambian (ubicación, SKU, lote: actual -> después):")
    for (loc, pid, lot), d in sorted(delta.items(), key=lambda kv: (str(codes.get(kv[0][0])), str(skus.get(kv[0][1])))):
        if abs(d) < 1e-9:
            continue
        bal = await db[Collections.INVENTORY_BALANCES].find_one(
            {"location_id": loc, "product_id": pid, "lot_number": lot}
        )
        actual = (bal or {}).get("quantity_on_hand", 0) or 0
        code, tipo = codes.get(loc, (loc, "?"))
        print(f"  {code} ({tipo}) {skus.get(pid, pid)} lote={lot!r}: {actual:g} -> {actual + d:g}")


async def main(tenant_id: str, apply: bool, reset_semanal: bool) -> None:
    movs = await movimientos_a_revertir(tenant_id, solo_huerfanos=not reset_semanal)
    await _informe(tenant_id, movs)
    if not apply:
        print("DRY-RUN: no se cambió nada. Repita con --apply.")
        return

    revertidos = await revertir(tenant_id, movs)
    print(f"Revertidos: {revertidos} movimientos.")
    if not reset_semanal:
        return

    db = tenant_db(tenant_id)
    for col in COLECCIONES_PEDIDOS:
        r = await db[col].delete_many({})
        print(f"  {col}: {r.deleted_count} borrados")
    # Import tardío: la sincronización arrastra el cliente HTTP de Defontana.
    from app.integrations.defontana import order_sync
    print("Re-sincronizando pedidos desde Defontana:", await order_sync.sync_orders(tenant_id))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reset-semanal", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.tenant, a.apply, a.reset_semanal))
