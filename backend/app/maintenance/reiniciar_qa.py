"""Reinicio de la etapa de pruebas contra el Defontana de QA (SOLO pruebas).

Defontana restaura su base de QA los fines de semana (copia de producción con ~1 semana de
desfase): los pedidos de la semana anterior cambian o desaparecen allá. Para que el WMS
"vuelva" junto con el ERP, el lunes se reinicia también acá.

El primer reinicio (cron del droplet, 2026-09-28) borraba pedidos y tareas pero **no tocaba
el inventario**: lo que las pruebas habían movido (bodega → staging → packing → despacho)
quedaba en STAGING/PACKING sin pedido que lo moviera, y con saldos negativos (el movimiento
de packing no lleva lote, así que un producto con lote dejaba +q en la fila con lote y −q en
la sin lote). Pasó el 2026-10-05: 19 u en STAGING, 7 en PACKING y 5 negativos.

Dos herramientas, con movimientos auditables:

- **Revertir** (``reverse_moves_for_reference``: inverso con el mismo lote, marca el original)
  los movimientos de picking/packing/despacho. Deja cada saldo exactamente como antes de la
  prueba **si nadie corrigió nada a mano entre medio**. El 2026-10-05 no era el caso: el 28/09
  se habían devuelto a mano 18 u de DISPATCH, y revertir las devolvía de nuevo (−18). Por eso
  la reversa no se aplica si dejaría algún saldo negativo.
- **Vaciar las ubicaciones operativas** (STAGING, PACKING, DISPATCH) mirando el saldo actual,
  no la historia: cuadra los pares del bug de lote (+q con lote / −q sin lote) con una
  corrección de lote, devuelve lo positivo a la ubicación de donde se pickeó y repone lo
  negativo desde ahí. Sin pedidos vivos, lo operativo tiene que quedar en cero.

Modos (todos dry-run salvo ``--apply``), en el contenedor del backend:

    python -m app.maintenance.reiniciar_qa --tenant <id>                      # vaciar operativas
    python -m app.maintenance.reiniciar_qa --tenant <id> --revertir-huerfanos # solo la reversa
    python -m app.maintenance.reiniciar_qa --tenant <id> --reset-semanal --apply

``--reset-semanal`` (el cron de los lunes, ``deploy/qa/wms-reset-pedidos-qa.sh``): revierte si es
seguro, borra pedidos/tareas/despachos/envíos, vacía lo operativo y re-sincroniza pedidos.

No toca productos, ubicaciones, recepciones, ajustes ni la conciliación. QUITAR el cron al
terminar la etapa de pruebas.
"""
import argparse
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from app.core.tenant_db import tenant_db
from app.core.utils import to_object_id
from app.models import Collections
from app.models.inventory import MovementType
from app.models.location import LocationType
from app.services import inventory_service

OPERATIVAS = (LocationType.STAGING.value, LocationType.PACKING.value, LocationType.DISPATCH.value)
ACTOR = "reinicio-qa"

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


async def negativos_tras_revertir(tenant_id: str, movs: List[Dict[str, Any]]) -> List[Tuple]:
    """Saldos que la reversa dejaría negativos (señal de correcciones manuales entre medio)."""
    db = tenant_db(tenant_id)
    malos = []
    for (loc, pid, lot), d in proyectar(movs).items():
        bal = await db[Collections.INVENTORY_BALANCES].find_one(
            {"location_id": loc, "product_id": pid, "lot_number": lot}
        )
        if ((bal or {}).get("quantity_on_hand", 0) or 0) + d < -1e-9:
            malos.append((loc, pid, lot))
    return malos


async def revertir(tenant_id: str, movs: List[Dict[str, Any]]) -> int:
    referencias = sorted({(m["reference_type"], m["reference_id"]) for m in movs})
    total = 0
    for ref_type, ref_id in referencias:
        total += await inventory_service.reverse_moves_for_reference(
            tenant_id=tenant_id, reference_type=ref_type, reference_id=ref_id,
            created_by="reinicio-qa", reason="Reinicio de pruebas QA: vuelve al stock previo",
        )
    return total


# ---------------------------------------------------------------------------
# Vaciar ubicaciones operativas
# ---------------------------------------------------------------------------

async def _origen(db, product_id: str, warehouse_id: str) -> Optional[str]:
    """Ubicación de bodega de donde salió el producto: la del último pick; si no hay, la de
    almacenamiento con más stock de él; si no, la primera de almacenamiento."""
    async for m in db[Collections.INVENTORY_MOVEMENTS].find(
        {"product_id": product_id, "movement_type": MovementType.PICK.value,
         "is_reversal": {"$ne": True}, "from_location_id": {"$ne": None}}
    ).sort("created_at", -1).limit(1):
        return m["from_location_id"]
    storage = [str(l["_id"]) async for l in db[Collections.LOCATIONS].find(
        {"warehouse_id": warehouse_id, "type": LocationType.STORAGE.value}, {"_id": 1})]
    mejor = None
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"product_id": product_id, "location_id": {"$in": storage}}
    ).sort("quantity_on_hand", -1).limit(1):
        mejor = b["location_id"]
    return mejor or (storage[0] if storage else None)


async def plan_vaciar(tenant_id: str) -> Dict[str, List[Dict[str, Any]]]:
    db = tenant_db(tenant_id)
    ops = {str(l["_id"]): l.get("warehouse_id") async for l in db[Collections.LOCATIONS].find(
        {"type": {"$in": list(OPERATIVAS)}}, {"warehouse_id": 1})}
    grupos: Dict[Tuple[str, str], Dict[Any, float]] = {}
    async for b in db[Collections.INVENTORY_BALANCES].find(
        {"location_id": {"$in": list(ops)}, "quantity_on_hand": {"$ne": 0}}
    ):
        g = grupos.setdefault((b["location_id"], b["product_id"]), {})
        lot = b.get("lot_number") or None
        g[lot] = g.get(lot, 0) + (b.get("quantity_on_hand") or 0)

    acciones: List[Dict[str, Any]] = []
    sin_resolver: List[Dict[str, Any]] = []
    for (loc, pid), lotes in grupos.items():
        wh = ops[loc]
        pos = {l: q for l, q in lotes.items() if q > 1e-9}
        neg = {l: -q for l, q in lotes.items() if q < -1e-9}
        # 1) Pares del bug de lote: +q con un lote, −q con otro (casi siempre "sin lote").
        for pl in list(pos):
            for nl in list(neg):
                q = min(pos[pl], neg[nl])
                if q <= 1e-9:
                    continue
                acciones.append({"tipo": "lote", "producto": pid, "bodega": wh, "ubicacion": loc,
                                 "de_lote": pl, "a_lote": nl, "cantidad": q})
                pos[pl] -= q
                neg[nl] -= q
        origen = await _origen(db, pid, wh)
        # 2) Lo positivo vuelve a la ubicación de origen, con su lote.
        for lot, q in pos.items():
            if q > 1e-9:
                if origen:
                    acciones.append({"tipo": "devolver", "producto": pid, "bodega": wh,
                                     "desde": loc, "hacia": origen, "lote": lot, "cantidad": q})
                else:
                    sin_resolver.append({"producto": pid, "ubicacion": loc, "lote": lot, "cantidad": q})
        # 3) Lo negativo se repone desde el origen (mismo lote si alcanza; si no, otro + corrección).
        for lot, q in neg.items():
            if q <= 1e-9:
                continue
            # Fuente en el origen: el mismo lote si alcanza; si no, cualquier saldo que alcance.
            candidatos = [
                b.get("lot_number") or None
                async for b in db[Collections.INVENTORY_BALANCES].find(
                    {"product_id": pid, "location_id": origen, "quantity_on_hand": {"$gte": q}}
                )
            ] if origen else []
            if not candidatos:
                sin_resolver.append({"producto": pid, "ubicacion": loc, "lote": lot, "cantidad": -q})
                continue
            fuente = lot if lot in candidatos else candidatos[0]
            acciones.append({"tipo": "reponer", "producto": pid, "bodega": wh,
                             "desde": origen, "hacia": loc, "lote": fuente, "cantidad": q})
            if fuente != lot:
                acciones.append({"tipo": "lote", "producto": pid, "bodega": wh, "ubicacion": loc,
                                 "de_lote": fuente, "a_lote": lot, "cantidad": q})
    return {"acciones": acciones, "sin_resolver": sin_resolver}


async def _mover(tenant_id: str, a: Dict[str, Any], tipo: str, desde: Optional[str],
                 hacia: Optional[str], lote_desde: Any, lote_hacia: Any, motivo: str) -> None:
    for loc, lot, delta in ((desde, lote_desde, -a["cantidad"]), (hacia, lote_hacia, a["cantidad"])):
        if loc:
            await inventory_service.change_location_stock(
                tenant_id=tenant_id, product_id=a["producto"], warehouse_id=a["bodega"],
                location_id=loc, delta=delta, lot_number=lot, allow_negative=True, notify=False,
            )
            await inventory_service.record_movement(
                tenant_id=tenant_id, movement_type=tipo, product_id=a["producto"],
                warehouse_id=a["bodega"], quantity=a["cantidad"],
                from_location_id=loc if delta < 0 else None,
                to_location_id=loc if delta > 0 else None,
                lot_number=lot, reference_type="mantencion", reason=motivo, created_by=ACTOR,
            )


async def vaciar(tenant_id: str, acciones: List[Dict[str, Any]]) -> int:
    for a in acciones:
        if a["tipo"] == "lote":
            await _mover(tenant_id, a, MovementType.LOT_CORRECTION.value, a["ubicacion"], a["ubicacion"],
                         a["de_lote"], a["a_lote"],
                         f"Reinicio QA: cuadra lote {a['de_lote']!r} -> {a['a_lote']!r} (packing sin lote)")
        else:
            await _mover(tenant_id, a, MovementType.TRANSFER.value, a["desde"], a["hacia"],
                         a["lote"], a["lote"],
                         "Reinicio QA: devuelve a bodega stock de pruebas sin pedido"
                         if a["tipo"] == "devolver" else
                         "Reinicio QA: repone saldo negativo de pruebas sin pedido")
    return len(acciones)


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


async def _informe_vaciar(tenant_id: str, plan: Dict[str, List[Dict[str, Any]]]) -> None:
    db = tenant_db(tenant_id)
    codes = {str(l["_id"]): l.get("code") async for l in db[Collections.LOCATIONS].find({}, {"code": 1})}
    skus = {str(p["_id"]): p.get("sku") async for p in db[Collections.PRODUCTS].find({}, {"sku": 1})}
    print(f"Vaciar operativas: {len(plan['acciones'])} acciones")
    for a in plan["acciones"]:
        sku = skus.get(a["producto"], a["producto"])
        if a["tipo"] == "lote":
            print(f"  [lote]    {codes.get(a['ubicacion'])} {sku}: {a['cantidad']:g} de lote "
                  f"{a['de_lote']!r} a {a['a_lote']!r}")
        else:
            print(f"  [{a['tipo']:<8}] {sku} lote={a['lote']!r}: {a['cantidad']:g} "
                  f"{codes.get(a['desde'])} -> {codes.get(a['hacia'])}")
    for r in plan["sin_resolver"]:
        print(f"  SIN RESOLVER: {skus.get(r['producto'])} en {codes.get(r['ubicacion'])} "
              f"lote={r['lote']!r}: {r['cantidad']:g} (no hay de dónde reponer)")


async def main(tenant_id: str, apply: bool, reset_semanal: bool = False,
               solo_revertir_huerfanos: bool = False) -> None:
    if solo_revertir_huerfanos or reset_semanal:
        movs = await movimientos_a_revertir(tenant_id, solo_huerfanos=not reset_semanal)
        await _informe(tenant_id, movs)
        malos = await negativos_tras_revertir(tenant_id, movs)
        if malos:
            print(f"La reversa dejaría {len(malos)} saldo(s) negativo(s): hubo correcciones a mano "
                  "entre medio. NO se revierte; lo operativo se vacía mirando el saldo actual.")
            movs = []
        if apply and movs:
            print(f"Revertidos: {await revertir(tenant_id, movs)} movimientos.")
        if solo_revertir_huerfanos and not reset_semanal:
            if not apply:
                print("DRY-RUN: no se cambió nada. Repita con --apply.")
            return

    if reset_semanal and apply:
        db = tenant_db(tenant_id)
        for col in COLECCIONES_PEDIDOS:
            r = await db[col].delete_many({})
            print(f"  {col}: {r.deleted_count} borrados")

    plan = await plan_vaciar(tenant_id)
    await _informe_vaciar(tenant_id, plan)
    if not apply:
        print("DRY-RUN: no se cambió nada. Repita con --apply.")
        return
    print(f"Aplicadas: {await vaciar(tenant_id, plan['acciones'])} acciones.")

    if reset_semanal:
        # Import tardío: la sincronización arrastra el cliente HTTP de Defontana.
        from app.integrations.defontana import order_sync
        print("Re-sincronizando pedidos desde Defontana:", await order_sync.sync_orders(tenant_id))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reset-semanal", action="store_true")
    ap.add_argument("--revertir-huerfanos", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.tenant, a.apply, a.reset_semanal, a.revertir_huerfanos))
