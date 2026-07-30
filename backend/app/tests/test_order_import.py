"""Tests for the PDF quotation import: parsing, catalog matching and order creation."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import get_database
from app.models import Collections
from app.schemas.order_import import ConfirmLine, ParsedOrderDraft, ParsedOrderLine
from app.services import order_service
from app.services.pdf_order_parser import _ocr_available, parse_document, parse_pdf, resolve_draft

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "cotizacion_7889.pdf"
PEDIDO_FIXTURE = Path(__file__).parent / "fixtures" / "pedido_2856.pdf"


def _pdf_bytes() -> bytes:
    return FIXTURE.read_bytes()


async def test_parse_fixture_header_and_lines():
    draft = parse_pdf(_pdf_bytes())

    assert draft.source == "pdf_digital"
    assert draft.doc_type == "cotizacion"
    assert draft.erp_order_number == "7889"
    assert "villarrica" in (draft.customer or "").lower()
    assert draft.customer_rut == "61.602.248-2"
    assert draft.order_date == "8-7-2026"
    assert draft.document_warnings == []

    assert len(draft.lines) == 11
    first = draft.lines[0]
    assert first.sku == "3MDS4930C"
    assert first.ordered_quantity == 40
    assert first.unit == "UN"
    assert "DISCOS SOFLEX" in (first.name or "")

    # Line 8 repeats line 1's SKU and carries a per-line comment.
    eighth = draft.lines[7]
    assert eighth.sku == "3MDS4930C"
    assert eighth.comments == ["medida a eleccion"]


async def test_parse_pedido_format():
    # A "Pedido" uses the same Defontana template as a "Cotización"; only the
    # document-type word (and a couple of header labels) differ.
    draft = parse_pdf(PEDIDO_FIXTURE.read_bytes())

    assert draft.source == "pdf_digital"
    assert draft.doc_type == "pedido"
    assert draft.erp_order_number == "2856"
    assert "gendarmeria" in (draft.customer or "").lower()
    assert draft.customer_rut == "61.004.000-4"
    assert draft.order_date == "10-7-2026"
    assert draft.document_warnings == []

    assert len(draft.lines) == 1
    assert draft.lines[0].sku == "ANES008"
    assert draft.lines[0].ordered_quantity == 40
    assert draft.lines[0].unit == "UN"


async def test_parse_then_resolve_against_catalog():
    db = get_database()
    tenant = "t-import"
    # Only two of the quotation's SKUs exist in the catalog.
    await db[Collections.PRODUCTS].insert_many(
        [
            {"tenant_id": tenant, "sku": "3MDS4930C", "name": "DISCO SOFLEX 4930C", "is_active": True},
            {"tenant_id": tenant, "sku": "DTIPS003", "name": "MICROAPLICADOR MEDIANO", "is_active": True},
        ]
    )

    draft = await resolve_draft(parse_pdf(_pdf_bytes()), tenant)
    by_sku = {ln.sku: ln for ln in draft.lines}

    # Both lines that carry SKU 3MDS4930C match; the repeat is flagged.
    matched_3m = [ln for ln in draft.lines if ln.sku == "3MDS4930C"]
    assert all(ln.match_status == "matched" and ln.match_by == "sku" for ln in matched_3m)
    assert any("repetido" in w.lower() for ln in matched_3m for w in ln.warnings)

    assert by_sku["DTIPS003"].match_status == "matched"
    # A SKU that isn't in the catalog stays unmatched for the reviewer to resolve.
    assert by_sku["DTIPS002"].match_status == "unmatched"
    assert by_sku["PINCEL002"].match_status == "unmatched"


async def test_resolve_matching_variants():
    db = get_database()
    tenant = "t-match"
    p_sku = await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": tenant, "sku": "ABC123", "name": "GUANTES NITRILO", "is_active": True}
    )
    p_bc = await db[Collections.PRODUCTS].insert_one(
        {"tenant_id": tenant, "sku": "SKUONLY", "name": "MASCARILLA", "is_active": True}
    )
    await db[Collections.BARCODES].insert_one(
        {"tenant_id": tenant, "product_id": str(p_bc.inserted_id), "barcode": "7791234567890", "is_active": True}
    )
    # Two products share a name -> name match is ambiguous.
    await db[Collections.PRODUCTS].insert_many(
        [
            {"tenant_id": tenant, "sku": "DUP1", "name": "ALGODON PRENSADO", "is_active": True},
            {"tenant_id": tenant, "sku": "DUP2", "name": "ALGODON PRENSADO", "is_active": True},
        ]
    )

    draft = ParsedOrderDraft(
        lines=[
            ParsedOrderLine(sku="ABC123", name="GUANTES", unit="UN", ordered_quantity=5),
            ParsedOrderLine(sku="7791234567890", name="X", unit="UN", ordered_quantity=2),
            ParsedOrderLine(sku="NOPE", name="ALGODON PRENSADO", unit="UN", ordered_quantity=1),
            ParsedOrderLine(sku="ZZZ", name="COSA INEXISTENTE QWERTY", unit="UN", ordered_quantity=1),
            ParsedOrderLine(sku="ABC123", name="X", unit="UN", ordered_quantity=0),
        ]
    )
    resolved = await resolve_draft(draft, tenant)
    l0, l1, l2, l3, l4 = resolved.lines

    assert l0.match_status == "matched" and l0.match_by == "sku"
    assert l0.product_id == str(p_sku.inserted_id)

    assert l1.match_status == "matched" and l1.match_by == "barcode"
    assert l1.sku == "SKUONLY"  # rewritten to the product's SKU

    assert l2.match_status == "ambiguous" and len(l2.candidates) == 2

    assert l3.match_status == "unmatched"

    assert l4.match_status == "invalid"  # quantity <= 0


async def test_confirm_creates_order_and_dedup(monkeypatch):
    monkeypatch.setattr(settings, "erp_sync_enabled", True)  # exercise the ERP push path
    db = get_database()
    tenant = "t-create"
    lines = [
        ConfirmLine(sku="ABC123", name="Guantes", unit="UN", ordered_quantity=5),
        ConfirmLine(sku="XYZ999", name="Mascarilla", unit="UN", ordered_quantity=2),
    ]
    doc = await order_service.create_order_from_lines(
        tenant_id=tenant,
        erp_order_number="7889",
        customer="Hospital Villarrica",
        lines=lines,
        created_by="user-1",
        source_document={"type": "cotizacion_pdf", "folio": "7889", "customer_rut": "61.602.248-2"},
    )

    assert doc["status"] == "imported"
    assert doc["erp_order_number"] == "7889"
    assert doc["customer"] == "Hospital Villarrica"
    assert len(doc["lines"]) == 2
    assert doc["source_document"]["folio"] == "7889"

    # ERP push job was enqueued with the Defontana-shaped payload.
    job = await db[Collections.SYNC_JOBS].find_one({"tenant_id": tenant, "job_type": "create_order"})
    assert job is not None
    assert job["payload"]["Number"] == "7889"
    assert len(job["payload"]["Detail"]) == 2

    # Same folio again -> 409.
    with pytest.raises(HTTPException) as exc:
        await order_service.create_order_from_lines(
            tenant_id=tenant,
            erp_order_number="7889",
            customer="Hospital Villarrica",
            lines=lines,
            created_by="user-1",
        )
    assert exc.value.status_code == 409


async def test_confirm_standalone_does_not_enqueue():
    # In stand-alone mode (erp_sync_enabled=False, the default) no ERP job is queued.
    db = get_database()
    tenant = "t-standalone"
    await order_service.create_order_from_lines(
        tenant_id=tenant,
        erp_order_number="8000",
        customer="Cliente X",
        lines=[ConfirmLine(sku="AAA", name="algo", unit="UN", ordered_quantity=1)],
        created_by="user-1",
    )
    assert await db[Collections.SYNC_JOBS].find_one({"tenant_id": tenant, "job_type": "create_order"}) is None


async def test_parse_rejects_non_pdf():
    with pytest.raises(ValueError):
        parse_pdf(b"esto no es un pdf")


@pytest.mark.skipif(not _ocr_available(), reason="OCR/Tesseract no disponible en este entorno")
async def test_ocr_pipeline_on_rendered_image():
    # Render the digital fixture to a clean PNG and run the OCR path end to end.
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(_pdf_bytes())
    pil = doc[0].render(scale=3).to_pil()
    doc.close()
    buf = io.BytesIO()
    pil.save(buf, format="PNG")

    draft = parse_document(buf.getvalue(), content_type="image/png", filename="cotizacion.png")
    assert draft.source == "ocr"
    assert draft.erp_order_number == "7889"
    assert len(draft.lines) >= 8  # OCR of a clean render should recover most of the 11 lines
