from typing import Any, Dict

from fastapi import HTTPException, status

from app.core.database import get_database
from app.core.security import create_access_token, verify_password
from app.core.utils import now_utc, serialize
from app.models import Collections


def user_public(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    data = serialize(user_doc)
    return {
        "id": data["id"],
        "tenant_id": data.get("tenant_id"),
        "name": data.get("name"),
        "email": data.get("email"),
        "role": data.get("role"),
        "allowed_warehouse_ids": data.get("allowed_warehouse_ids", []) or [],
        "is_active": data.get("is_active", True),
    }


async def login(email: str, password: str) -> Dict[str, Any]:
    # Pre-authentication: the tenant is not known yet, so this is intentionally not
    # tenant-scoped. Email is unique *per tenant*, not globally, so once a second
    # company exists the same address could resolve to two accounts — refuse rather
    # than silently sign into an arbitrary tenant.
    db = get_database()
    matches = await db[Collections.USERS].find({"email": email}).to_list(length=2)
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este correo está registrado en más de una empresa; contacta al administrador",
        )
    user = matches[0] if matches else None
    if not user or not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    await db[Collections.USERS].update_one(
        {"_id": user["_id"]}, {"$set": {"last_login_at": now_utc()}}
    )

    token = create_access_token(
        subject=str(user["_id"]),
        extra={"tenant_id": user.get("tenant_id"), "role": user.get("role")},
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_public(user),
    }
