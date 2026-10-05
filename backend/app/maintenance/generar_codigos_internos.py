"""Genera el EAN-13 interno de los productos que no tienen ningún código de barras.

Los códigos de barras son del WMS (Defontana no los entrega). Hasta el 2026-10-05 solo se
generaban al importar el "Informe de Artículos"; los productos que entraron por el Excel
genérico, el alta manual o la sincronización quedaron sin código (126 en DEV, 124 con stock):
sin etiqueta, y en picking solo se escaneaban escribiendo el SKU.

Idempotente y dry-run por defecto. En el contenedor del backend:

    python -m app.maintenance.generar_codigos_internos --tenant <id>
    python -m app.maintenance.generar_codigos_internos --tenant <id> --apply
"""
import argparse
import asyncio

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.services.product_import_service import ensure_internal_barcode


async def sin_codigo(tenant_id: str) -> list:
    db = tenant_db(tenant_id)
    con = set(await db[Collections.BARCODES].distinct("product_id"))
    return [p async for p in db[Collections.PRODUCTS].find({}, {"sku": 1, "name": 1})
            if str(p["_id"]) not in con]


async def main(tenant_id: str, apply: bool) -> int:
    productos = await sin_codigo(tenant_id)
    print(f"Productos sin código de barras: {len(productos)}")
    for p in productos[:20]:
        print(f"  {p.get('sku')}  {(p.get('name') or '')[:50]}")
    if not apply:
        print("DRY-RUN: no se generó nada. Repita con --apply.")
        return 0
    db = tenant_db(tenant_id)
    hechos = 0
    for p in productos:
        hechos += await ensure_internal_barcode(
            db, tenant_id, str(p["_id"]), p.get("sku") or "", "mantencion", now_utc()
        )
    print(f"Generados: {hechos}. Siguen sin código: {len(await sin_codigo(tenant_id))}")
    return hechos


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.tenant, a.apply))
