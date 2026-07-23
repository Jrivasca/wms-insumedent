"""Parse an INSUMEDENT quotation PDF ("Cotización", Defontana template) into an
order draft, and match its lines against the tenant's product catalog.

Calibrated against 190+ real quotations. The layout is a fixed Defontana template:

    Folio N° <n>
    Señor (es) | Ciudad | Giro | R.U.T          (label band)
    <customer> | <city> | <giro> | <rut>         (value band, may wrap a line)
    ...
    Item Código Detalle Cant P. Unitario Rec/Desc Total   (line table header)
    1 <SKU> <detail...> <qty> <unit> $ <price> $ <recdesc> $ <total>
    Comentario: <per-line note>                  (optional, attached to prev line)

Header fields (customer) are read geometrically via word positions because the
plain-text linearization mixes columns; line items are read with a regex anchored
on the three trailing money columns, which is robust to spaces inside the detail.
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import List, Optional

import pdfplumber

from app.core.database import get_database
from app.core.utils import to_object_id
from app.models import Collections
from app.schemas.order_import import (
    MATCH_AMBIGUOUS,
    MATCH_INVALID,
    MATCH_MATCHED,
    MATCH_UNMATCHED,
    LineCandidate,
    ParsedOrderDraft,
    ParsedOrderLine,
)

# RUT of the issuer (INSUMEDENT SPA). Used to tell the customer RUT apart from the
# issuer's, which is printed at the top of every document.
EMISOR_RUT = "76.712.267-5"

_FOLIO_RE = re.compile(r"Folio\s*N[°ºo]?\s*:?\s*(\d+)", re.IGNORECASE)
_RUT_RE = re.compile(r"\d{1,2}\.\d{3}\.\d{3}-[\dkK]")
_DATE_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b")

_MONEY = r"\$\s*[\d.,\-]+"
_LINE_RE = re.compile(
    r"^\s*(?P<item>\d{1,3})\s+"
    r"(?P<code>\S+)\s+"
    r"(?P<detail>.*?)\s+"
    r"(?P<qty>[\d.,]+)\s+"
    r"(?P<unit>[A-Za-z][A-Za-z0-9.]{0,4})\s+"
    + _MONEY + r"\s+" + _MONEY + r"\s+" + _MONEY + r"\s*$"
)
_COMMENT_RE = re.compile(r"^\s*Comentario\s*:\s*(.+)$", re.IGNORECASE)

# Labels used to bound the customer cell geometrically.
_RIGHT_LABELS = ("Ciudad", "Giro", "R.U.T")
_NEXT_BAND = ("Dirección", "Condición", "Vendedor", "Tipo", "Comuna", "Item")


def parse_quantity(raw: str) -> Optional[float]:
    """Parse a Chilean-formatted quantity ("1.200" -> 1200, "1,5" -> 1.5)."""
    s = (raw or "").strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):        # thousands separators
        return float(re.sub(r"[.,]", "", s))
    if re.fullmatch(r"\d+,\d+", s):                    # decimal comma
        return float(s.replace(",", "."))
    if re.fullmatch(r"\d+(\.\d+)?", s):                # plain / decimal dot
        return float(s)
    return None


def _norm(s: Optional[str]) -> str:
    """Uppercase, strip accents and collapse spaces for name comparison."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def _customer_from_page(page) -> Optional[str]:
    """Extract the "Señor (es)" value cell using word geometry."""
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return None
    anchor = next((w for w in words if w["text"].startswith("Señor")), None)
    if anchor is None:
        return None
    top, x0 = anchor["top"], anchor["x0"]

    same_row = [w for w in words if abs(w["top"] - top) < 4 and w["x0"] > x0 + 2]
    right_xs = [w["x0"] for w in same_row if any(w["text"].startswith(l) for l in _RIGHT_LABELS)]
    right_x = min(right_xs) if right_xs else min((w["x0"] for w in same_row), default=x0 + 180)

    next_tops = [
        w["top"] for w in words
        if w["top"] > top + 4 and any(w["text"].startswith(l) for l in _NEXT_BAND)
    ]
    bottom = min(next_tops) if next_tops else top + 40

    cell = [w for w in words if top + 4 < w["top"] < bottom - 1 and x0 - 2 <= w["x0"] < right_x - 2]
    cell.sort(key=lambda w: (round(w["top"]), w["x0"]))

    # Keep only the first two rows of the cell (the name never spills further).
    rows: List[int] = []
    for w in cell:
        r = round(w["top"])
        if r not in rows:
            rows.append(r)
    keep = set(rows[:2])
    tokens = [w["text"] for w in cell if round(w["top"]) in keep]

    # Trim any "giro" bleed: institution names are all-caps, the giro is sentence-case.
    clean: List[str] = []
    for t in tokens:
        if re.search(r"[a-záéíóúñ]", t):
            break
        clean.append(t)
    name = re.sub(r"\s+", " ", " ".join(clean or tokens)).strip()
    return name or None


def _parse_lines(text: str) -> List[ParsedOrderLine]:
    lines: List[ParsedOrderLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m:
            qty = parse_quantity(m.group("qty"))
            lines.append(
                ParsedOrderLine(
                    raw_text=line,
                    item=int(m.group("item")),
                    sku=m.group("code"),
                    name=m.group("detail").strip() or None,
                    unit=m.group("unit"),
                    ordered_quantity=qty,
                )
            )
            continue
        cm = _COMMENT_RE.match(line)
        if cm and lines:
            lines[-1].comments.append(cm.group(1).strip())
    return lines


def parse_pdf(file_bytes: bytes) -> ParsedOrderDraft:
    """Parse the PDF into a draft (no DB access). Raises ``ValueError`` if unreadable."""
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("No se pudo leer el PDF (archivo dañado o no es un PDF).") from exc

    with pdf:
        pages = pdf.pages
        full_text = "\n".join((p.extract_text() or "") for p in pages)
        customer = _customer_from_page(pages[0]) if pages else None

    draft = ParsedOrderDraft(source="pdf_digital")

    if not full_text.strip():
        # No embedded text: almost certainly a scan or phone photo (OCR is phase 2).
        draft.document_warnings.append(
            "No se detectó texto en el PDF (posible imagen/escaneo). "
            "Ingresa las líneas manualmente o sube el PDF digital."
        )
        return draft

    m = _FOLIO_RE.search(full_text)
    draft.erp_order_number = m.group(1) if m else None
    draft.customer = customer
    draft.customer_rut = next((r for r in _RUT_RE.findall(full_text) if r != EMISOR_RUT), None)
    dm = _DATE_RE.search(full_text)  # first date printed = "Fecha Documento"
    draft.order_date = dm.group(1) if dm else None
    draft.lines = _parse_lines(full_text)

    if not draft.erp_order_number:
        draft.document_warnings.append("No se detectó el Folio; ingrésalo manualmente.")
    if not draft.customer:
        draft.document_warnings.append("No se detectó el cliente; ingrésalo manualmente.")
    if not draft.lines:
        draft.document_warnings.append(
            "No se detectaron líneas de producto. Revisa que sea una cotización INSUMEDENT."
        )
    return draft


async def resolve_draft(draft: ParsedOrderDraft, tenant_id: str) -> ParsedOrderDraft:
    """Match each parsed line against the catalog (SKU -> barcode -> name)."""
    db = get_database()

    # Warn on repeated SKUs (real in the samples: same product on two lines).
    seen: dict = {}
    for ln in draft.lines:
        if ln.sku:
            seen[ln.sku] = seen.get(ln.sku, 0) + 1

    for ln in draft.lines:
        if ln.ordered_quantity is None or ln.ordered_quantity <= 0:
            ln.match_status = MATCH_INVALID
            ln.warnings.append("Cantidad no válida; corrígela antes de crear.")
            continue
        if ln.sku and seen.get(ln.sku, 0) > 1:
            ln.warnings.append("SKU repetido en el documento.")

        code = (ln.sku or "").strip()
        # 1) Exact SKU.
        product = None
        if code:
            product = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": code})
        if product:
            ln.product_id = str(product["_id"])
            ln.match_status = MATCH_MATCHED
            ln.match_by = "sku"
            continue

        # 2) Barcode (in case the Código column carries a barcode instead of a SKU).
        if code:
            bc = await db[Collections.BARCODES].find_one(
                {"tenant_id": tenant_id, "barcode": code, "is_active": True}
            )
            if bc:
                product = await db[Collections.PRODUCTS].find_one(
                    {"_id": to_object_id(bc["product_id"]), "tenant_id": tenant_id}
                )
                if product:
                    ln.product_id = str(product["_id"])
                    ln.sku = product.get("sku") or code
                    ln.match_status = MATCH_MATCHED
                    ln.match_by = "barcode"
                    continue

        # 3) Name fallback (normalized exact, then a bounded contains search).
        candidates = await _match_by_name(db, tenant_id, ln.name)
        if len(candidates) == 1:
            ln.product_id = candidates[0].product_id
            ln.match_status = MATCH_MATCHED
            ln.match_by = "name"
        elif len(candidates) > 1:
            ln.candidates = candidates
            ln.match_status = MATCH_AMBIGUOUS
            ln.warnings.append("Varios productos coinciden por nombre; elige uno.")
        else:
            ln.match_status = MATCH_UNMATCHED
            ln.warnings.append("SKU/nombre no encontrado en el catálogo; búscalo u omite la línea.")

    return draft


async def _match_by_name(db, tenant_id: str, name: Optional[str]) -> List[LineCandidate]:
    if not name:
        return []
    target = _norm(name)
    if len(target) < 4:
        return []
    cursor = db[Collections.PRODUCTS].find(
        {"tenant_id": tenant_id, "name": {"$regex": re.escape(name), "$options": "i"}}
    )
    rows = await cursor.to_list(length=6)
    exact = [r for r in rows if _norm(r.get("name")) == target]
    chosen = exact or rows
    return [
        LineCandidate(product_id=str(r["_id"]), sku=r.get("sku", ""), name=r.get("name", ""))
        for r in chosen[:5]
    ]
