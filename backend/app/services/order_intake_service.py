"""Folder-watch order intake (Plan 1, Fase 1).

Reuses the existing PDF parser/matcher (``pdf_order_parser``) and order creator
(``order_service.create_order_from_lines``) to turn a file dropped in a synced
cloud folder into an order, using a **hybrid** policy:

- every line matched + a valid folio  -> create the order directly (ready for picking);
- any ambiguous/unmatched/invalid line -> park a draft in ``order_import_drafts``
  (review queue) that the existing review UI resolves before creating the order.

``process_bytes`` is HTTP-independent so the worker (``folder_intake``) can call it
headless; ``intake_runs`` keeps per-file idempotency (dedupe by content hash).
"""
import hashlib
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.notification import NotificationType
from app.schemas.order_import import MATCH_MATCHED, OrderImportConfirm
from app.services import notification_service, order_service, pdf_order_parser

logger = get_logger(__name__)

DRAFT_STATUS_PENDING = "pending_review"


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _auto_eligible(draft) -> bool:
    """A parsed draft can become an order with no human review only when the folio
    is present and *every* line matched a real product with a positive quantity."""
    if not (draft.erp_order_number or "").strip():
        return False
    if not draft.lines:
        return False
    for ln in draft.lines:
        if ln.match_status != MATCH_MATCHED or not ln.product_id:
            return False
        if not ln.ordered_quantity or ln.ordered_quantity <= 0:
            return False
    return True


async def _already_processed(db, file_hash: str) -> bool:
    return await db[Collections.INTAKE_RUNS].find_one({"file_hash": file_hash}) is not None


async def _record_run(db, file_name: str, file_hash: str, outcome: str, detail: Optional[str] = None) -> None:
    await db[Collections.INTAKE_RUNS].update_one(
        {"file_hash": file_hash},
        {"$set": {"file_name": file_name, "outcome": outcome, "detail": detail, "processed_at": now_utc()}},
        upsert=True,
    )


async def process_bytes(
    *, tenant_id: str, file_name: str, data: bytes, source: str = "folder_intake"
) -> Dict[str, Any]:
    """Parse ``data`` and either create the order or queue a review draft.

    Idempotent per file content: a hash already recorded in ``intake_runs`` is
    skipped. Never raises for parse/business errors — records the outcome and
    returns it so the caller can move the file accordingly."""
    db = tenant_db(tenant_id)
    file_hash = _file_hash(data)
    if await _already_processed(db, file_hash):
        return {"outcome": "duplicate", "file_name": file_name}

    try:
        draft = pdf_order_parser.parse_document(data, None, file_name)
        draft = await pdf_order_parser.resolve_draft(draft, tenant_id)
    except Exception as exc:  # noqa: BLE001 - parse/OCR failures go to the "revisar" folder
        await _record_run(db, file_name, file_hash, "error", str(exc))
        logger.warning("intake: no se pudo leer %s: %s", file_name, exc)
        return {"outcome": "error", "file_name": file_name, "detail": str(exc)}

    folio = (draft.erp_order_number or "").strip()

    if _auto_eligible(draft):
        try:
            order = await order_service.create_order_from_lines(
                tenant_id=tenant_id,
                erp_order_number=folio,
                customer=draft.customer,
                lines=list(draft.lines),
                created_by=source,
                source_document={
                    "type": "folder_intake",
                    "doc_type": draft.doc_type,
                    "folio": folio,
                    "customer_rut": draft.customer_rut,
                    "doc_date": draft.order_date,
                    "file_name": file_name,
                },
            )
            await _record_run(db, file_name, file_hash, "created", folio)
            return {"outcome": "created", "order_id": order["id"], "folio": folio}
        except HTTPException as exc:
            if exc.status_code == 409:  # folio ya existe -> no duplicar
                await _record_run(db, file_name, file_hash, "skipped", "el folio ya existe")
                return {"outcome": "skipped", "folio": folio, "detail": "el folio ya existe"}
            raise

    # Needs a human: store the resolved draft in the review queue.
    problem = sum(1 for ln in draft.lines if ln.match_status != MATCH_MATCHED)
    now = now_utc()
    doc = {
        "status": DRAFT_STATUS_PENDING,
        "erp_order_number": folio or None,
        "customer": draft.customer,
        "customer_rut": draft.customer_rut,
        "order_date": draft.order_date,
        "doc_type": draft.doc_type,
        "source": draft.source,
        "draft": draft.model_dump(),
        "line_count": len(draft.lines),
        "problem_lines": problem,
        "file_name": file_name,
        "file_hash": file_hash,
        "created_at": now,
        "created_by": source,
    }
    result = await db[Collections.ORDER_IMPORT_DRAFTS].insert_one(doc)
    draft_id = str(result.inserted_id)
    await _record_run(db, file_name, file_hash, "review", folio)
    await notification_service.emit(
        tenant_id=tenant_id,
        notification_type=NotificationType.IMPORT_REVIEW.value,
        title=f"Pedido por revisar {folio}".strip(),
        body=f"{draft.customer or 'Sin cliente'} · {problem} línea(s) a resolver",
        entity_type="import_draft",
        entity_id=draft_id,
        metadata={"folio": folio, "problem_lines": problem, "file_name": file_name},
    )
    return {"outcome": "review", "draft_id": draft_id, "folio": folio, "problem_lines": problem}


# ---------------------------------------------------------------------------
# Review-queue read/actions (used by the routes + the review UI)
# ---------------------------------------------------------------------------
def _summary(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": data["id"],
        "erp_order_number": data.get("erp_order_number"),
        "customer": data.get("customer"),
        "line_count": data.get("line_count"),
        "problem_lines": data.get("problem_lines"),
        "file_name": data.get("file_name"),
        "doc_type": data.get("doc_type"),
        "created_at": data.get("created_at"),
    }


async def list_drafts(tenant_id: str) -> List[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    cursor = (
        db[Collections.ORDER_IMPORT_DRAFTS]
        .find({"status": DRAFT_STATUS_PENDING})
        .sort("created_at", -1)
    )
    return [_summary(serialize(d)) for d in await cursor.to_list(length=200)]


async def unresolved_count(tenant_id: str) -> int:
    db = tenant_db(tenant_id)
    return await db[Collections.ORDER_IMPORT_DRAFTS].count_documents({"status": DRAFT_STATUS_PENDING})


async def get_draft(tenant_id: str, draft_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    doc = await db[Collections.ORDER_IMPORT_DRAFTS].find_one({"_id": to_object_id(draft_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Borrador de importación no encontrado")
    data = serialize(doc)
    # Return the ParsedOrderDraft shape the review UI already understands, plus ids.
    return {"id": data["id"], "file_name": data.get("file_name"), **data["draft"]}


async def confirm_draft(
    tenant_id: str, draft_id: str, payload: OrderImportConfirm, actor: str
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    doc = await db[Collections.ORDER_IMPORT_DRAFTS].find_one({"_id": to_object_id(draft_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Borrador de importación no encontrado")
    order = await order_service.create_order_from_lines(
        tenant_id=tenant_id,
        erp_order_number=payload.erp_order_number,
        customer=payload.customer,
        lines=payload.lines,
        created_by=actor,
        source_document={
            "type": "folder_intake_review",
            "doc_type": payload.doc_type,
            "folio": payload.erp_order_number,
            "customer_rut": payload.customer_rut,
            "doc_date": payload.order_date,
            "file_name": doc.get("file_name"),
        },
    )
    await db[Collections.ORDER_IMPORT_DRAFTS].delete_one({"_id": doc["_id"]})
    return order


async def discard_draft(tenant_id: str, draft_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    result = await db[Collections.ORDER_IMPORT_DRAFTS].delete_one({"_id": to_object_id(draft_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Borrador de importación no encontrado")
    return {"discarded": True}
