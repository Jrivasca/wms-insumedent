"""Import an order from an INSUMEDENT quotation PDF.

Two steps:
  - ``POST /orders/import/parse``   -> parse + match, returns a draft (no persistence)
  - ``POST /orders/import/confirm`` -> create the order from the reviewed draft
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import CurrentUser, require_roles
from app.schemas.order_import import OrderImportConfirm, ParsedOrderDraft
from app.services import order_intake_service, order_service, pdf_order_parser
from app.services.audit_service import log_action

router = APIRouter(prefix="/orders/import", tags=["orders"])

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
# Accept PDFs (digital or scanned) and images (phone photos). Some browsers send a
# PDF as application/octet-stream, so we also accept by extension / magic bytes.
ALLOWED_CONTENT_TYPES = {"application/pdf", "application/octet-stream", "binary/octet-stream"}
ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic")


@router.post("/parse", response_model=ParsedOrderDraft)
async def parse_order_pdf(
    file: UploadFile = File(...), user: CurrentUser = Depends(require_roles("supervisor", "sales"))
) -> ParsedOrderDraft:
    ctype = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    allowed = (
        ctype in ALLOWED_CONTENT_TYPES
        or ctype.startswith("image/")
        or fname.endswith(ALLOWED_EXTENSIONS)
    )
    if not allowed:
        raise HTTPException(
            status_code=415,
            detail="Sube una cotización en PDF o una foto/escaneo (JPG/PNG).",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el tamaño máximo (10 MB).")

    try:
        draft = pdf_order_parser.parse_document(data, file.content_type, file.filename)
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
            "type": "pdf_import",
            "doc_type": payload.doc_type,  # cotizacion | pedido | ...
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


# --- Cola de revisión del folder-watch (Plan 1 Fase 1) ---------------------
@router.get("/drafts")
async def list_import_drafts(
    user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
    return await order_intake_service.list_drafts(user.tenant_id)


@router.get("/drafts/count")
async def import_drafts_count(
    user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
    return {"count": await order_intake_service.unresolved_count(user.tenant_id)}


@router.get("/drafts/{draft_id}")
async def get_import_draft(
    draft_id: str, user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
    return await order_intake_service.get_draft(user.tenant_id, draft_id)


@router.post("/drafts/{draft_id}/confirm", status_code=201)
async def confirm_import_draft(
    draft_id: str,
    payload: OrderImportConfirm,
    user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
    doc = await order_intake_service.confirm_draft(user.tenant_id, draft_id, payload, user.id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="order_import",
        entity_type="order",
        entity_id=doc["id"],
        metadata={"erp_order_number": payload.erp_order_number, "source": "folder_intake_review"},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return doc


@router.post("/drafts/{draft_id}/discard")
async def discard_import_draft(
    draft_id: str, user: CurrentUser = Depends(require_roles("supervisor", "sales")),
):
    result = await order_intake_service.discard_draft(user.tenant_id, draft_id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="order_import_discard",
        entity_type="import_draft",
        entity_id=draft_id,
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result
