"""Excel catalog importer (Plan 1, Fase 2): header mapping, all-or-nothing on a
missing SKU, upsert + barcodes, the 24 h staleness reminder, and tenant isolation."""
import io
from datetime import timedelta

import pytest
from openpyxl import Workbook

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections
from app.services import product_import_service

pytestmark = pytest.mark.asyncio


def _xlsx(headers, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _product_count(tenant_id: str) -> int:
    return await tenant_db(tenant_id)[Collections.PRODUCTS].count_documents({})


# ---------------------------------------------------------------------------
async def test_import_creates_then_updates_and_adds_barcode():
    tid = "tA"
    data = _xlsx(
        ["Código", "Nombre", "Código de barras", "Categoría"],
        [["SKU-1", "Guantes M", "7801234567890", "Insumos"],
         ["SKU-2", "Mascarillas", "", "Insumos"]],
    )
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] and rep["created"] == 2 and rep["barcodes_added"] == 1
    assert await _product_count(tid) == 2

    # Re-import with a changed name and a new barcode -> update, not duplicate.
    data2 = _xlsx(
        ["Código", "Nombre", "Código de barras"],
        [["SKU-1", "Guantes Medianos", "7801234567890"],  # same barcode -> not re-added
         ["SKU-2", "Mascarillas KN95", "7809999999999"]],
    )
    rep2 = await product_import_service.import_xlsx(tid, data2, actor="u1")
    assert rep2["applied"] and rep2["updated"] == 2 and rep2["created"] == 0
    assert rep2["barcodes_added"] == 1  # only SKU-2's new barcode
    assert await _product_count(tid) == 2  # no duplicates
    prod = await tenant_db(tid)[Collections.PRODUCTS].find_one({"sku": "SKU-1"})
    assert prod["name"] == "Guantes Medianos"


async def test_all_or_nothing_when_a_row_lacks_sku():
    tid = "tA"
    data = _xlsx(
        ["Código", "Nombre"],
        [["SKU-1", "Ok"], ["", "Sin código"], ["SKU-3", "Ok3"]],
    )
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] is False
    assert rep["rejected"] and rep["rejected"][0]["row"] == 2
    assert await _product_count(tid) == 0  # nada se aplicó


async def test_missing_sku_column_is_rejected():
    tid = "tA"
    data = _xlsx(["Nombre", "Precio"], [["Algo", 1000]])
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] is False and "SKU" in rep["error"]
    assert await _product_count(tid) == 0


async def test_empty_rows_are_skipped():
    tid = "tA"
    data = _xlsx(["Código", "Nombre"], [["SKU-1", "Ok"], [None, None], ["", ""]])
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] and rep["rows"] == 1 and rep["created"] == 1


# ---------------------------------------------------------------------------
async def test_staleness_reminder_fresh_then_stale_then_deduped():
    tid = "tA"
    await product_import_service.import_xlsx(tid, _xlsx(["Código", "Nombre"], [["SKU-1", "Ok"]]), actor="u1")

    # Recién importado -> no alerta.
    assert await product_import_service.catalog_staleness_check(tid) is False

    # Envejecer el último import a 30 h atrás -> alerta una vez.
    db = tenant_db(tid)
    await db[Collections.CATALOG_IMPORT_STATE].update_one(
        {}, {"$set": {"last_import_at": now_utc() - timedelta(hours=30)}}
    )
    assert await product_import_service.catalog_staleness_check(tid) is True
    # Segunda pasada inmediata -> deduplicado.
    assert await product_import_service.catalog_staleness_check(tid) is False


async def test_import_reads_legacy_xls():
    xlwt = pytest.importorskip("xlwt")  # se saltea si xlwt no está instalado
    tid = "tA"
    wb = xlwt.Workbook()
    ws = wb.add_sheet("s")
    for col, h in enumerate(["Código", "Nombre", "Código de barras"]):
        ws.write(0, col, h)
    ws.write(1, 0, "SKU-XLS")
    ws.write(1, 1, "Guante formato viejo")
    ws.write(1, 2, "7801111111118")
    buf = io.BytesIO()
    wb.save(buf)
    rep = await product_import_service.import_xlsx(tid, buf.getvalue(), actor="u1")
    assert rep["applied"] and rep["created"] == 1 and rep["barcodes_added"] == 1
    assert await _product_count(tid) == 1


async def test_import_is_tenant_isolated():
    a, b = "tA", "tB"
    await product_import_service.import_xlsx(a, _xlsx(["Código", "Nombre"], [["SKU-1", "Ok"]]), actor="u1")
    assert await _product_count(a) == 1
    assert await _product_count(b) == 0
