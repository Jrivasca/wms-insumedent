from typing import List

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, require_supervisor
from app.schemas.auth import UserCreate, UserPublic, UserUpdate
from app.services import user_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=List[UserPublic])
async def list_users(user: CurrentUser = Depends(require_supervisor)):
    return await user_service.list_users(user.tenant_id)


@router.post("", response_model=UserPublic, status_code=201)
async def create_user(payload: UserCreate, user: CurrentUser = Depends(require_supervisor)):
    created = await user_service.create_user(user.tenant_id, payload, user.id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="create_user",
        entity_type="user",
        entity_id=created["id"],
        after={"email": created["email"], "role": created["role"]},
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return created


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: str, user: CurrentUser = Depends(get_current_user)):
    return await user_service.get_user(user.tenant_id, user_id)


@router.patch("/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: str, payload: UserUpdate, user: CurrentUser = Depends(require_supervisor)
):
    updated = await user_service.update_user(user.tenant_id, user_id, payload, user.id)
    await log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="update_user",
        entity_type="user",
        entity_id=user_id,
        ip=user.ip,
        user_agent=user.user_agent,
    )
    return updated
