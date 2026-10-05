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
    # SKU-1 trae el suyo; SKU-2 no trae y recibe el EAN-13 interno del WMS.
    assert rep["applied"] and rep["created"] == 2 and rep["barcodes_added"] == 2
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


def _con_escape_crudo(data: bytes, marca: str, crudo: str) -> bytes:
    """Reemplaza ``marca`` por ``crudo`` dentro del XML del .xlsx, como lo deja Excel."""
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            contenido = src.read(item.filename)
            if item.filename.endswith(".xml"):
                contenido = contenido.replace(marca.encode(), crudo.encode())
            dst.writestr(item, contenido)
    return out.getvalue()


async def test_el_tabulador_escapado_de_excel_no_queda_en_el_nombre():
    """2026-10-05: el export de artículos de Defontana trae "_x0009_" (tabulador) y el nombre
    quedaba "LIMAS K 31MM 06 ROGIN_x0009_"."""
    tid = "tEsc"
    data = _xlsx(["Código", "Nombre"], [["LIMASK3106", "LIMAS K 31MM 06 ROGINTABMARCA"],
                                        ["LIT-1", "LITERALMARCA"]])
    data = _con_escape_crudo(data, "TABMARCA", "_x0009_")
    data = _con_escape_crudo(data, "LITERALMARCA", "A_x005F_x0009_B")
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["applied"] and rep["created"] == 2
    db = tenant_db(tid)[Collections.PRODUCTS]
    assert (await db.find_one({"sku": "LIMASK3106"}))["name"] == "LIMAS K 31MM 06 ROGIN"
    # "_x005F_" es el escape del propio "_x": queda el texto literal.
    assert (await db.find_one({"sku": "LIT-1"}))["name"] == "A_x0009_B"


# ---------------------------------------------------------------------------
# Los códigos de barras son del WMS: todo producto recibe su EAN-13 interno
# ---------------------------------------------------------------------------
async def _codigos(tid, sku):
    db = tenant_db(tid)
    p = await db[Collections.PRODUCTS].find_one({"sku": sku})
    return [b async for b in db[Collections.BARCODES].find({"product_id": str(p["_id"])})]


async def test_el_excel_generico_sin_codigos_genera_el_interno():
    """2026-10-05: el export de artículos (columnas) no traía códigos y no se generaban."""
    tid = "tGen"
    data = _xlsx(["Código", "Nombre"], [["GEN-1", "Producto uno"], ["GEN-2", "Producto dos"]])
    rep = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep["barcodes_added"] == 2
    bc = await _codigos(tid, "GEN-1")
    assert len(bc) == 1 and bc[0]["type"] == "internal" and len(bc[0]["barcode"]) == 13
    # Re-importar no duplica.
    rep2 = await product_import_service.import_xlsx(tid, data, actor="u1")
    assert rep2["barcodes_added"] == 0 and len(await _codigos(tid, "GEN-1")) == 1


async def test_si_el_interno_choca_con_otro_usa_una_variante():
    tid = "tChoque"
    db = tenant_db(tid)
    ocupado = product_import_service._internal_ean13("CHOCA")
    otro = await db[Collections.PRODUCTS].insert_one({"tenant_id": tid, "sku": "OTRO", "name": "x"})
    await db[Collections.BARCODES].insert_one(
        {"tenant_id": tid, "product_id": str(otro.inserted_id), "barcode": ocupado})
    p = await db[Collections.PRODUCTS].insert_one({"tenant_id": tid, "sku": "CHOCA", "name": "y"})
    assert await product_import_service.ensure_internal_barcode(
        db, tid, str(p.inserted_id), "CHOCA", "u1", now_utc())
    bc = await _codigos(tid, "CHOCA")
    assert len(bc) == 1 and bc[0]["barcode"] != ocupado


async def test_mantencion_completa_los_que_no_tienen_codigo():
    from app.maintenance import generar_codigos_internos

    tid = "tMant"
    db = tenant_db(tid)
    for sku in ("M-1", "M-2"):
        await db[Collections.PRODUCTS].insert_one({"tenant_id": tid, "sku": sku, "name": sku})
    assert await generar_codigos_internos.main(tid, apply=False) == 0
    assert len(await generar_codigos_internos.sin_codigo(tid)) == 2
    assert await generar_codigos_internos.main(tid, apply=True) == 2
    assert await generar_codigos_internos.sin_codigo(tid) == []
