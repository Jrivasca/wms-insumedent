"""Import an order from an INSUMEDENT quotation PDF.

Two steps:
  - ``POST /orders/import/parse``   -> parse + match, returns a draft (no persistence)
  - ``POST /orders/import/confirm`` -> create the order from the reviewed draft
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import CurrentUser, require_roles
from app.schemas.order_import import OrderImportConfirm, ParsedOrderDraft
from app.services import order_service, pdf_order_parser
from app.services.audit_service import log_action

router = APIRouter(prefix="/orders/import", tags=["orders"])

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
# Some browsers send a PDF as application/octet-stream; we also accept by extension.
PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream", "binary/octet-stream"}


@router.post("/parse", response_model=ParsedOrderDraft)
async def parse_order_pdf(
    file: UploadFile = File(...), user: CurrentUser = Depends(require_roles("supervisor", "sales"))
) -> ParsedOrderDraft:
    ctype = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    if ctype not in PDF_CONTENT_TYPES and not fname.endswith(".pdf"):
        raise HTTPException(
            status_code=415,
            detail="Sube un archivo PDF. (La lectura de fotos/imágenes llega en la próxima etapa.)",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el tamaño máximo (10 MB).")

    try:
        draft = pdf_order_parser.parse_pdf(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await pdf_order_parser.resolve_draft(draft, user.tenant_id)


@router.post("/confirm", status_code=201)
async def confirm_order_import(
    payload: OrderImportConfirm, user: CurrentUser = Depends(require_roles("supervisor", "sales"))
):
    doc = await order_service.create_order_from_lines(
        tenant_id=user.tenant_id,
        erp_order_number=payload.erp_order_number,
        customer=payload.customer,
        lines=payload.lines,
        created_by=user.id,
        source_document={
            "type": "cotizacion_pdf",
            "folio": payload.erp_order_number,
            "customer_rut": payload.customer_rut,
            "doc_date": payload.order_date,
        },
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="order_import",
        entity_type="order",
        entity_id=doc["id"],
        metadata={"erp_order_number": payload.erp_order_number, "source": "pdf"},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return doc
