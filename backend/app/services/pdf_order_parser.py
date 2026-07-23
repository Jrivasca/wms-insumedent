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

try:  # OCR stack (phase 2). pypdfium2 + Pillow ship with pdfplumber; pytesseract is new.
    import pypdfium2 as pdfium
    import pytesseract
    from PIL import Image
    _OCR_LIBS = True
except Exception:  # pragma: no cover
    _OCR_LIBS = False

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

# Tolerant to OCR noise between "Folio" and the number (e.g. "N°" read as "N*").
_FOLIO_RE = re.compile(r"Folio[^\d\n]{0,8}(\d{3,6})", re.IGNORECASE)
_RUT_RE = re.compile(r"\d{1,2}\.\d{3}\.\d{3}-[\dkK]")
_DATE_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b")

# The "$" is optional: OCR frequently drops it on the first money columns.
_MONEY = r"\$?\s*[\d.,\-]+"
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


OCR_LANG = "spa"


def _ocr_available() -> bool:
    """True if pytesseract and the Tesseract binary are usable."""
    if not _OCR_LIBS:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_image_bytes(image_bytes: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("No se pudo abrir la imagen.") from exc
    return pytesseract.image_to_string(img, lang=OCR_LANG)


def _ocr_pdf_bytes(pdf_bytes: bytes) -> str:
    """Render each PDF page to a bitmap and OCR it (scanned PDFs)."""
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        out = []
        for i in range(len(doc)):
            pil = doc[i].render(scale=3).to_pil()  # ~216 DPI
            out.append(pytesseract.image_to_string(pil, lang=OCR_LANG))
        return "\n".join(out)
    finally:
        doc.close()


def _customer_from_text(text: str) -> Optional[str]:
    """Best-effort customer from a flat text blob (OCR path, no word geometry).

    The value is on the line following the "Señor (es) | Ciudad | Giro | R.U.T"
    label row. We strip any RUT that bled in and cap the length; the exact name is
    hard to isolate from the city/giro on the same OCR line, so the operator edits it.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.match(r"(?i)se[nñ]or", ln):
            after = re.sub(r"(?i)^se[nñ]or\s*\(?\s*e?s?\s*\)?\.?\s*", "", ln).strip()
            if not after or re.search(r"(?i)\b(ciudad|giro|r\.?u\.?t)\b", after):
                after = lines[i + 1] if i + 1 < len(lines) else ""
            after = _RUT_RE.sub("", after).strip()
            after = re.sub(r"\s+", " ", after)[:60].strip()
            return after or None
    return None


def _build_draft_from_text(full_text: str, customer: Optional[str], source: str) -> ParsedOrderDraft:
    """Header + lines extraction shared by the digital and OCR paths."""
    draft = ParsedOrderDraft(source=source)
    m = _FOLIO_RE.search(full_text)
    draft.erp_order_number = m.group(1) if m else None
    draft.customer = customer
    draft.customer_rut = next((r for r in _RUT_RE.findall(full_text) if r != EMISOR_RUT), None)
    dm = _DATE_RE.search(full_text)  # first date printed = "Fecha Documento"
    draft.order_date = dm.group(1) if dm else None
    draft.lines = _parse_lines(full_text)

    if source == "ocr":
        draft.document_warnings.append(
            "Documento leído por OCR (foto/escaneo): revisa con cuidado folio, cliente y cada línea."
        )
    if not draft.erp_order_number:
        draft.document_warnings.append("No se detectó el Folio; ingrésalo manualmente.")
    if not draft.customer:
        draft.document_warnings.append("No se detectó el cliente; ingrésalo manualmente.")
    if not draft.lines:
        draft.document_warnings.append(
            "No se detectaron líneas de producto. Revisa el documento o ingrésalas a mano."
        )
    return draft


def _looks_like_pdf(file_bytes: bytes) -> bool:
    return file_bytes[:1024].lstrip()[:4] == b"%PDF"


def _looks_like_image(file_bytes: bytes, content_type: Optional[str], filename: Optional[str]) -> bool:
    if (content_type or "").lower().startswith("image/"):
        return True
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext in {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "heic"}:
        return True
    sig = file_bytes[:12]
    return (
        sig[:3] == b"\xff\xd8\xff"                       # JPEG
        or sig[:8] == b"\x89PNG\r\n\x1a\n"               # PNG
        or (sig[:4] == b"RIFF" and b"WEBP" in sig)       # WEBP
    )


def _parse_pdf_document(file_bytes: bytes) -> ParsedOrderDraft:
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("No se pudo leer el PDF (archivo dañado o no es un PDF).") from exc

    with pdf:
        pages = pdf.pages
        full_text = "\n".join((p.extract_text() or "") for p in pages)
        customer = _customer_from_page(pages[0]) if pages else None

    if full_text.strip():
        return _build_draft_from_text(full_text, customer, source="pdf_digital")

    # No embedded text -> scanned PDF. OCR the rendered pages when possible.
    if not _ocr_available():
        draft = ParsedOrderDraft(source="pdf_digital")
        draft.document_warnings.append(
            "No se detectó texto en el PDF (posible escaneo) y el OCR no está disponible. "
            "Sube el PDF digital o ingresa las líneas a mano."
        )
        return draft
    text = _ocr_pdf_bytes(file_bytes)
    return _build_draft_from_text(text, _customer_from_text(text), source="ocr")


def parse_pdf(file_bytes: bytes) -> ParsedOrderDraft:
    """Backwards-compatible entry for PDFs (digital, or scanned via OCR)."""
    return _parse_pdf_document(file_bytes)


def parse_document(
    file_bytes: bytes, content_type: Optional[str] = None, filename: Optional[str] = None
) -> ParsedOrderDraft:
    """Parse a PDF (digital or scanned) or an image (phone photo) into a draft."""
    if not file_bytes:
        raise ValueError("El archivo está vacío.")
    if _looks_like_image(file_bytes, content_type, filename) and not _looks_like_pdf(file_bytes):
        if not _ocr_available():
            raise ValueError(
                "La lectura de fotos/imágenes requiere OCR y no está disponible en el servidor."
            )
        text = _ocr_image_bytes(file_bytes)
        return _build_draft_from_text(text, _customer_from_text(text), source="ocr")
    return _parse_pdf_document(file_bytes)


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
