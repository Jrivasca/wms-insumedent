from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats(user: CurrentUser = Depends(get_current_user)):
    return await dashboard_service.get_stats(user.tenant_id)
