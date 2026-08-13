"""Folder-watch order intake (Plan 1, Fase 1): hybrid auto-create vs review queue,
draft actions, per-file idempotency, error handling and tenant isolation. The PDF
parser is monkeypatched, so these run without a real PDF/OCR."""
import pytest
from bson import ObjectId

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.schemas.order_import import (
    MATCH_MATCHED,
    MATCH_UNMATCHED,
    ConfirmLine,
    OrderImportConfirm,
    ParsedOrderDraft,
    ParsedOrderLine,
)
from app.services import notification_service, order_intake_service, pdf_order_parser

pytestmark = pytest.mark.asyncio


def _install_parser(monkeypatch, draft: ParsedOrderDraft):
    monkeypatch.setattr(pdf_order_parser, "parse_document", lambda data, ct, name: draft)

    async def _resolve(d, tenant_id):
        return draft

    monkeypatch.setattr(pdf_order_parser, "resolve_draft", _resolve)


def _matched_line(product_id: str, sku="SKU1", qty=2.0) -> ParsedOrderLine:
    return ParsedOrderLine(
        sku=sku, name="Producto 1", ordered_quantity=qty,
        match_status=MATCH_MATCHED, match_by="sku", product_id=product_id,
    )


def _unmatched_line(sku="SKUX", qty=1.0) -> ParsedOrderLine:
    return ParsedOrderLine(sku=sku, name="Desconocido", ordered_quantity=qty, match_status=MATCH_UNMATCHED)


async def _product(tenant_id: str, sku="SKU1") -> str:
    db = get_database()
    r = await db[Collections.PRODUCTS].insert_one({"tenant_id": tenant_id, "sku": sku, "name": "Producto 1"})
    return str(r.inserted_id)


async def _order_exists(tenant_id: str, folio: str) -> bool:
    db = tenant_db(tenant_id)
    return await db[Collections.ORDERS].find_one({"erp_order_number": folio}) is not None


# ---------------------------------------------------------------------------
async def test_auto_create_when_all_lines_matched(monkeypatch):
    tid = "tenantA"
    pid = await _product(tid)
    draft = ParsedOrderDraft(erp_order_number="8001", customer="ACME", lines=[_matched_line(pid)])
    _install_parser(monkeypatch, draft)

    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="a.pdf", data=b"PDF-A")
    assert res["outcome"] == "created"
    assert await _order_exists(tid, "8001")
    assert await order_intake_service.unresolved_count(tid) == 0


async def test_review_queue_when_a_line_is_unmatched(monkeypatch):
    tid = "tenantA"
    pid = await _product(tid)
    draft = ParsedOrderDraft(
        erp_order_number="8002", customer="ACME",
        lines=[_matched_line(pid), _unmatched_line()],
    )
    _install_parser(monkeypatch, draft)

    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="b.pdf", data=b"PDF-B")
    assert res["outcome"] == "review"
    assert res["problem_lines"] == 1
    assert not await _order_exists(tid, "8002")  # no se creó todavía

    drafts = await order_intake_service.list_drafts(tid)
    assert len(drafts) == 1 and drafts[0]["erp_order_number"] == "8002"
    full = await order_intake_service.get_draft(tid, drafts[0]["id"])
    assert len(full["lines"]) == 2 and "id" in full


async def test_review_when_folio_missing(monkeypatch):
    tid = "tenantA"
    pid = await _product(tid)
    draft = ParsedOrderDraft(erp_order_number=None, customer="ACME", lines=[_matched_line(pid)])
    _install_parser(monkeypatch, draft)
    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="c.pdf", data=b"PDF-C")
    assert res["outcome"] == "review"  # sin folio no se auto-crea


async def test_confirm_draft_creates_order_and_removes_draft(monkeypatch):
    tid = "tenantA"
    pid = await _product(tid)
    draft = ParsedOrderDraft(
        erp_order_number="8003", customer="ACME",
        lines=[_matched_line(pid), _unmatched_line()],
    )
    _install_parser(monkeypatch, draft)
    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="d.pdf", data=b"PDF-D")
    draft_id = res["draft_id"]

    payload = OrderImportConfirm(
        erp_order_number="8003", customer="ACME",
        lines=[ConfirmLine(sku="SKU1", ordered_quantity=2, product_id=pid)],
    )
    order = await order_intake_service.confirm_draft(tid, draft_id, payload, actor="u1")
    assert order["erp_order_number"] == "8003"
    assert await _order_exists(tid, "8003")
    assert await order_intake_service.unresolved_count(tid) == 0


async def test_discard_draft(monkeypatch):
    tid = "tenantA"
    draft = ParsedOrderDraft(erp_order_number="8004", lines=[_unmatched_line()])
    _install_parser(monkeypatch, draft)
    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="e.pdf", data=b"PDF-E")
    assert (await order_intake_service.discard_draft(tid, res["draft_id"]))["discarded"] is True
    assert await order_intake_service.unresolved_count(tid) == 0


async def test_idempotent_by_content_hash(monkeypatch):
    tid = "tenantA"
    pid = await _product(tid)
    draft = ParsedOrderDraft(erp_order_number="8005", lines=[_matched_line(pid)])
    _install_parser(monkeypatch, draft)
    first = await order_intake_service.process_bytes(tenant_id=tid, file_name="f.pdf", data=b"SAME")
    second = await order_intake_service.process_bytes(tenant_id=tid, file_name="f-copy.pdf", data=b"SAME")
    assert first["outcome"] == "created"
    assert second["outcome"] == "duplicate"


async def test_parse_error_outcome(monkeypatch):
    tid = "tenantA"

    def _boom(data, ct, name):
        raise ValueError("no se pudo leer")

    monkeypatch.setattr(pdf_order_parser, "parse_document", _boom)
    res = await order_intake_service.process_bytes(tenant_id=tid, file_name="bad.pdf", data=b"XX")
    assert res["outcome"] == "error"


async def test_drafts_are_tenant_isolated(monkeypatch):
    a, b = "tenantA", "tenantB"
    draft = ParsedOrderDraft(erp_order_number="8006", lines=[_unmatched_line()])
    _install_parser(monkeypatch, draft)
    await order_intake_service.process_bytes(tenant_id=a, file_name="g.pdf", data=b"PDF-G")
    assert await order_intake_service.unresolved_count(a) == 1
    assert await order_intake_service.unresolved_count(b) == 0
    assert await order_intake_service.list_drafts(b) == []
