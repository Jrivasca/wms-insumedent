from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.services import push_service

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def vapid_public_key(user: CurrentUser = Depends(get_current_user)):
    return {"key": settings.vapid_public_key, "enabled": settings.push_enabled}


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: PushSubscriptionIn, user: CurrentUser = Depends(get_current_user)
):
    await push_service.subscribe(
        user.tenant_id,
        user.id,
        payload.endpoint,
        payload.keys.model_dump(),
        user_agent=user.user_agent,
    )
    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(
    payload: PushUnsubscribeIn, user: CurrentUser = Depends(get_current_user)
):
    removed = await push_service.unsubscribe(user.tenant_id, user.id, payload.endpoint)
    return {"removed": removed}
