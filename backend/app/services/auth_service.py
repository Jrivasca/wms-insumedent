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
    db = get_database()
    user = await db[Collections.USERS].find_one({"email": email})
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
