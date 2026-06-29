from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.services import sync_job_service

router = APIRouter(prefix="/sync-jobs", tags=["sync-jobs"])


@router.get("")
async def list_jobs(
    status: Optional[str] = None, user: CurrentUser = Depends(get_current_user)
):
    return await sync_job_service.list_jobs(user.tenant_id, status)


@router.post("/{job_id}/retry")
async def retry(job_id: str, user: CurrentUser = Depends(require_supervisor)):
    return await sync_job_service.retry(user.tenant_id, job_id)


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, user: CurrentUser = Depends(require_supervisor)):
    return await sync_job_service.cancel(user.tenant_id, job_id)
