from dataclasses import dataclass, field
from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_database
from app.core.security import decode_access_token
from app.core.utils import serialize, to_object_id
from app.models import Collections
from app.models.user import SUPERVISOR_ROLES

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    tenant_id: str
    name: str
    email: str
    role: str
    allowed_warehouse_ids: List[str] = field(default_factory=list)
    ip: Optional[str] = None
    user_agent: Optional[str] = None

    @property
    def is_supervisor(self) -> bool:
        return self.role in SUPERVISOR_ROLES

    @property
    def warehouse_scoped(self) -> bool:
        """True when this user may only see/operate a subset of warehouses.

        Admins and supervisors always see every warehouse; an empty
        ``allowed_warehouse_ids`` also means "no restriction".
        """
        return bool(self.allowed_warehouse_ids) and not self.is_supervisor

    def can_access_warehouse(self, warehouse_id: Optional[str]) -> bool:
        if not self.warehouse_scoped:
            return True
        return warehouse_id in self.allowed_warehouse_ids

    def assert_warehouse_allowed(self, warehouse_id: Optional[str]) -> None:
        if not self.can_access_warehouse(warehouse_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a esta bodega",
            )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token"
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )

    db = get_database()
    user = await db[Collections.USERS].find_one({"_id": to_object_id(payload["sub"])})
    if user is None or not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )

    data = serialize(user)
    return CurrentUser(
        id=data["id"],
        tenant_id=data["tenant_id"],
        name=data.get("name", ""),
        email=data.get("email", ""),
        role=data.get("role", ""),
        allowed_warehouse_ids=data.get("allowed_warehouse_ids", []) or [],
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def require_roles(*roles: str):
    """Dependency factory enforcing that the current user has one of ``roles``.

    ``admin`` always passes.
    """
    allowed = set(roles)

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != "admin" and user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action",
            )
        return user

    return checker


async def require_supervisor(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_supervisor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor role required"
        )
    return user
