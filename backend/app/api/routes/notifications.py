from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    return await notification_service.list_for_user(
        user.tenant_id, user.id, unread_only=unread, limit=limit, offset=offset
    )


@router.get("/unread-count")
async def unread_count(user: CurrentUser = Depends(get_current_user)):
    return {"count": await notification_service.unread_count(user.tenant_id, user.id)}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: CurrentUser = Depends(get_current_user)):
    updated = await notification_service.mark_read(user.tenant_id, user.id, notification_id)
    return {"updated": updated}


@router.post("/read-all")
async def mark_all_read(user: CurrentUser = Depends(get_current_user)):
    updated = await notification_service.mark_all_read(user.tenant_id, user.id)
    return {"updated": updated}
