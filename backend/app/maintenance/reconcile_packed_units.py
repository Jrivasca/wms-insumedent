"""Limpieza de unidades empacadas huérfanas (secuela del bug 1).

Antes del fix, un escaneo de packing sin bulto sumaba a ``quantity_packed`` sin registrar la unidad
en ningún bulto: quedaba "empacada" pero huérfana. Este script reconcilia cada línea de packing con
lo realmente contenido en sus bultos: baja ``quantity_packed`` a la suma de unidades que sí están en
algún bulto y recomputa el estado de la línea. Lo que ya estaba consistente no se toca.

Es idempotente y **por defecto solo reporta** (dry-run). Se corre a mano, no automáticamente:

    docker compose exec -T backend python -m app.maintenance.reconcile_packed_units          # reporta
    docker compose exec -T backend python -m app.maintenance.reconcile_packed_units --apply  # aplica

Usa ``get_database()`` a propósito (mantenimiento cross-tenant, como ``seed.py``).
"""
import asyncio
import sys

from app.core.database import get_database
from app.core.utils import now_utc
from app.models import Collections
from app.models.packing import PackingLineStatus


def _units_in_packages(packages):
    """Unidades realmente contenidas en los bultos, por SKU."""
    by_sku: dict = {}
    for pkg in packages or []:
        for item in pkg.get("items") or []:
            sku = item.get("sku")
            by_sku[sku] = by_sku.get(sku, 0) + (item.get("quantity") or 0)
    return by_sku


async def reconcile(apply: bool) -> None:
    db = get_database()
    tasks_changed = lines_changed = 0
    async for task in db[Collections.PACKING_TASKS].find({}):
        real_by_sku = _units_in_packages(task.get("packages", []))
        changed = False
        for line in task.get("lines", []):
            real = real_by_sku.get(line.get("sku"), 0)
            packed = line.get("quantity_packed") or 0
            if packed > real:  # hay unidades huérfanas
                lines_changed += 1
                changed = True
                print(f"  task {task.get('_id')} tenant {task.get('tenant_id')} "
                      f"sku {line.get('sku')}: quantity_packed {packed} -> {real}")
                line["quantity_packed"] = real
                required = line.get("quantity_required", 0)
                if real <= 0:
                    line["status"] = PackingLineStatus.PENDING.value
                elif real >= required:
                    line["status"] = PackingLineStatus.PACKED.value
                else:
                    line["status"] = PackingLineStatus.PARTIAL.value
        if changed:
            tasks_changed += 1
            if apply:
                await db[Collections.PACKING_TASKS].update_one(
                    {"_id": task["_id"]},
                    {"$set": {"lines": task["lines"], "updated_at": now_utc()}},
                )
    print(f"{'APLICADO' if apply else 'DRY-RUN (sin cambios)'}: "
          f"{tasks_changed} tarea(s) y {lines_changed} línea(s) con unidades huérfanas.")


if __name__ == "__main__":
    asyncio.run(reconcile(apply="--apply" in sys.argv))
