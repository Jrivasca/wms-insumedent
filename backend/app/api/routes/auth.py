from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user
from app.schemas.auth import LoginRequest, LoginResponse, UserPublic
from app.services import auth_service
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    result = await auth_service.login(payload.email, payload.password)
    await log_action(
        tenant_id=result["user"]["tenant_id"],
        user_id=result["user"]["id"],
        action="login",
        entity_type="user",
        entity_id=result["user"]["id"],
    )
    return result


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "allowed_warehouse_ids": user.allowed_warehouse_ids,
        "is_active": True,
    }


@router.post("/logout")
async def logout(user: CurrentUser = Depends(get_current_user)):
    # JWT is stateless; logout is handled client-side by discarding the token.
    return {"status": "ok"}
