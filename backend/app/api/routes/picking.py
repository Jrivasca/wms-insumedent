from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.schemas.picking import (
    CompletePickingRequest,
    MarkMissingRequest,
    ResetLineRequest,
    ScanRequest,
)
from app.services import picking_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/picking", tags=["picking"])


@router.get("/tasks")
async def list_tasks(
    assigned_to: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await picking_service.list_tasks(
        user.tenant_id, user, assigned_to, status, limit, offset
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: CurrentUser = Depends(get_current_user)):
    return await picking_service.get_task(user.tenant_id, task_id)


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str, user: CurrentUser = Depends(get_current_user)):
    return await picking_service.start_task(user.tenant_id, task_id, user)


@router.post("/tasks/{task_id}/scan")
async def scan(
    task_id: str, payload: ScanRequest, user: CurrentUser = Depends(get_current_user)
):
    return await picking_service.scan(
        user.tenant_id, task_id, user, payload.barcode, payload.quantity, payload.location_id
    )


@router.post("/tasks/{task_id}/mark-missing")
async def mark_missing(
    task_id: str, payload: MarkMissingRequest, user: CurrentUser = Depends(get_current_user)
):
    result = await picking_service.mark_missing(
        user.tenant_id, task_id, user, payload.sku, payload.reason
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="picking_mark_missing",
        entity_type="picking_task",
        entity_id=task_id,
        metadata={"sku": payload.sku, "reason": payload.reason},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/tasks/{task_id}/reset-line")
async def reset_line(
    task_id: str, payload: ResetLineRequest, user: CurrentUser = Depends(get_current_user)
):
    result = await picking_service.reset_line(
        user.tenant_id, task_id, user, payload.sku
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="picking_reset_line",
        entity_type="picking_task",
        entity_id=task_id,
        metadata={"sku": payload.sku},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/tasks/{task_id}/complete")
async def complete(
    task_id: str,
    payload: CompletePickingRequest = CompletePickingRequest(),
    user: CurrentUser = Depends(get_current_user),
):
    result = await picking_service.complete(
        user.tenant_id, task_id, user, payload.allow_partial
    )
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="picking_complete",
        entity_type="picking_task",
        entity_id=task_id,
        metadata={"allow_partial": payload.allow_partial, "status": result.get("status")},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result
