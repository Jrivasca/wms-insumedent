"""Schemas for importing an order from an INSUMEDENT PDF quotation.

The flow is two-step: ``/orders/import/parse`` returns a :class:`ParsedOrderDraft`
(no persistence) that the operator reviews/edits, and ``/orders/import/confirm``
receives an :class:`OrderImportConfirm` that is validated server-side and turned
into a real order via ``order_service.create_order_from_lines``.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

# Per-line match outcome shown in the review screen.
MATCH_MATCHED = "matched"
MATCH_AMBIGUOUS = "ambiguous"
MATCH_UNMATCHED = "unmatched"
MATCH_INVALID = "invalid"


class LineCandidate(BaseModel):
    """A product proposed for an ambiguous line."""

    product_id: str
    sku: str
    name: str


class ParsedOrderLine(BaseModel):
    """One detected line of the quotation, plus how it matched our catalog."""

    raw_text: Optional[str] = None
    item: Optional[int] = None
    sku: Optional[str] = None          # "Código" column of the PDF
    name: Optional[str] = None         # "Detalle" column of the PDF
    unit: str = "UN"
    ordered_quantity: Optional[float] = None
    match_status: str = MATCH_UNMATCHED
    match_by: Optional[str] = None     # sku | barcode | name | None
    product_id: Optional[str] = None
    candidates: List[LineCandidate] = []
    comments: List[str] = []           # per-line "Comentario:" rows from the PDF
    warnings: List[str] = []


class ParsedOrderDraft(BaseModel):
    """Result of parsing a PDF: header + lines. Not persisted."""

    erp_order_number: Optional[str] = None   # from "Folio N°"
    customer: Optional[str] = None           # from "Señor (es)"
    customer_rut: Optional[str] = None
    order_date: Optional[str] = None         # raw string as printed (d-m-Y)
    source: str = "pdf_digital"              # pdf_digital | ocr
    lines: List[ParsedOrderLine] = []
    document_warnings: List[str] = []


class ConfirmLine(BaseModel):
    """A reviewed line the operator confirmed for creation."""

    sku: str
    name: Optional[str] = None
    unit: str = "UN"
    ordered_quantity: float = Field(gt=0)
    product_id: Optional[str] = None


class OrderImportConfirm(BaseModel):
    """Edited draft posted back to create the order."""

    erp_order_number: str
    customer: Optional[str] = None
    customer_rut: Optional[str] = None
    order_date: Optional[str] = None
    lines: List[ConfirmLine]
