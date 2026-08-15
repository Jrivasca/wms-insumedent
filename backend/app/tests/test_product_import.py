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


# ---------------------------------------------------------------------------
# Defontana "Informe de Artículos": HTML disfrazado de .xls
# ---------------------------------------------------------------------------
def _defontana_html(products) -> bytes:
    """products = [(articulo_descripcion, stock, costo), ...]. Encoding cp1252 como
    el export real de Defontana (que además usa &nbsp; y <TD> en mayúsculas)."""
    head = (
        "<html><head><title>Informe de Artículos</title></head><body>"
        "<TABLE><TR><TD colspan='8'>Informe de Artículos</TD></TR>"
        "<TR><TD>Artículo - Descripción</TD><TD>Stock Disponible</TD>"
        "<TD>Costo Vigente $</TD><TD>Costo Reposición $</TD>"
        "<TD>Pendientes recepción</TD><TD>Pendientes de Entrega</TD>"
        "<TD>Stock Futuro</TD></TR>"
        "<TR><TD>Unidades</TD><TD>Fecha</TD><TD>Unidades en Pedidos Aprobados</TD></TR>"
    )
    body = ""
    for art, stock, costo in products:
        body += (
            f"<tr><TD class='BOD'>{art}</TD><TD>{stock}</TD><TD>{costo}</TD>"
            "<TD>0</TD><TD>0</TD><TD>&nbsp;</TD><TD>0</TD><TD>0</TD></TR>"
        )
    return (head + body + "</TABLE></body></html>").encode("cp1252")


async def test_import_defontana_html_xls_creates_catalog_with_internal_barcodes():
    tid = "tDefo"
    data = _defontana_html([
        ("0004357-KIT DE FRESAS MICRODONT ULTRA FINO", 2, "7,941"),
        ("3M-70-2014-1-RESINA FLUIDA A2", 5, "12,300"),
        ("1-ACIDO ORTOFOSFORICO SEITY", 0, "0"),
    ])
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] and rep["created"] == 3 and rep["barcodes_added"] == 3

    db = tenant_db(tid)
    # Split código/nombre correcto, incl. el prefijo 3M con guiones.
    p3m = await db[Collections.PRODUCTS].find_one({"sku": "3M-70-2014-1"})
    assert p3m is not None and p3m["name"] == "RESINA FLUIDA A2"
    kit = await db[Collections.PRODUCTS].find_one({"sku": "0004357"})
    assert kit is not None and kit["name"] == "KIT DE FRESAS MICRODONT ULTRA FINO"

    # Barcode interno: EAN13 de 13 dígitos, prefijo 20, tipo internal + fuente generated.
    bc = await db[Collections.BARCODES].find_one({"product_id": str(kit["_id"])})
    assert bc is not None and bc["barcode"].isdigit() and len(bc["barcode"]) == 13
    assert bc["barcode"].startswith("20") and bc["type"] == "internal" and bc["source"] == "generated"


async def test_reimport_defontana_is_idempotent_no_duplicate_barcodes():
    tid = "tDefo2"
    data = _defontana_html([("102152-CARISTOP 5000 PASTA X 51 G", 0, "5,211")])
    rep1 = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep1["created"] == 1 and rep1["barcodes_added"] == 1

    rep2 = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep2["applied"] and rep2["updated"] == 1 and rep2["created"] == 0
    assert rep2["barcodes_added"] == 0  # el EAN13 interno es determinístico -> no se re-agrega
    assert await _product_count(tid) == 1
    assert await tenant_db(tid)[Collections.BARCODES].count_documents({}) == 1


def test_split_code_name_heuristic():
    f = product_import_service._split_code_name
    assert f("0004357-KIT DE FRESAS MICRODONT") == ("0004357", "KIT DE FRESAS MICRODONT")
    assert f("0707-DIAMANTE REDONDA 801 008 BV.") == ("0707", "DIAMANTE REDONDA 801 008 BV.")
    assert f("1-ACIDO ORTOFOSFORICO SEITY") == ("1", "ACIDO ORTOFOSFORICO SEITY")
    # Código 3M con guiones: no se debe partir por el primer guion.
    assert f("3M-70-2014-1-RESINA FLUIDA A2") == ("3M-70-2014-1", "RESINA FLUIDA A2")
    # Sin segmento multi-palabra: cae al primer guion.
    assert f("ABC-GEL") == ("ABC", "GEL")
    assert f("") == ("", None)


def test_internal_ean13_is_valid_and_deterministic():
    f = product_import_service._internal_ean13
    code = f("3M-70-2014-1")
    assert len(code) == 13 and code.isdigit() and code.startswith("20")
    # Dígito verificador EAN13 correcto.
    assert product_import_service._ean13_check_digit(code[:12]) == code[12]
    # Determinístico por SKU.
    assert f("3M-70-2014-1") == code
    assert f("OTRO-SKU") != code
