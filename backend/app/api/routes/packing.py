from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.schemas.packing import CreatePackageRequest, PackScanRequest, ResetLineRequest
from app.services import packing_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/packing", tags=["packing"])


@router.get("/tasks")
async def list_tasks(
    assigned_to: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await packing_service.list_tasks(user.tenant_id, user, assigned_to)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: CurrentUser = Depends(get_current_user)):
    return await packing_service.get_task(user.tenant_id, task_id)


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: str, user: CurrentUser = Depends(get_current_user)):
    return await packing_service.start_task(user.tenant_id, task_id, user)


@router.post("/tasks/{task_id}/scan")
async def scan(
    task_id: str, payload: PackScanRequest, user: CurrentUser = Depends(get_current_user)
):
    return await packing_service.scan(
        user.tenant_id, task_id, user, payload.barcode, payload.quantity, payload.package_id
    )


@router.post("/tasks/{task_id}/create-package", status_code=201)
async def create_package(
    task_id: str,
    payload: CreatePackageRequest = CreatePackageRequest(),
    user: CurrentUser = Depends(get_current_user),
):
    return await packing_service.create_package(user.tenant_id, task_id, user, payload.label)


@router.post("/tasks/{task_id}/reset-line")
async def reset_line(
    task_id: str, payload: ResetLineRequest, user: CurrentUser = Depends(get_current_user)
):
    result = await packing_service.reset_line(user.tenant_id, task_id, user, payload.sku)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="packing_reset_line",
        entity_type="packing_task",
        entity_id=task_id,
        metadata={"sku": payload.sku},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result


@router.post("/tasks/{task_id}/complete")
async def complete(task_id: str, user: CurrentUser = Depends(get_current_user)):
    result = await packing_service.complete(user.tenant_id, task_id, user)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="packing_complete",
        entity_type="packing_task",
        entity_id=task_id,
        metadata={"status": result.get("status")},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return result
