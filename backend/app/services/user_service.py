from typing import Any, Dict, List

from fastapi import HTTPException

from app.core.tenant_db import tenant_db
from app.core.security import hash_password
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.schemas.auth import UserCreate, UserUpdate
from app.services.auth_service import user_public


async def list_users(tenant_id: str) -> List[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    cursor = db[Collections.USERS].find({"tenant_id": tenant_id}).sort("name", 1)
    return [user_public(u) for u in await cursor.to_list(length=500)]


async def get_user(tenant_id: str, user_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    user = await db[Collections.USERS].find_one(
        {"_id": to_object_id(user_id), "tenant_id": tenant_id}
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user_public(user)


async def create_user(tenant_id: str, data: UserCreate, actor: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    existing = await db[Collections.USERS].find_one(
        {"tenant_id": tenant_id, "email": data.email}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists for this tenant")

    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "name": data.name,
        "email": data.email,
        "password_hash": hash_password(data.password),
        "role": data.role.value,
        "allowed_warehouse_ids": data.allowed_warehouse_ids,
        "is_active": True,
        "last_login_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
    }
    result = await db[Collections.USERS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return user_public(doc)


async def update_user(
    tenant_id: str, user_id: str, data: UserUpdate, actor: str
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    user = await db[Collections.USERS].find_one(
        {"_id": to_object_id(user_id), "tenant_id": tenant_id}
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # --- Salvaguardas anti-bloqueo -------------------------------------------
    # get_current_user valida contra la base en cada request: desactivarte o
    # bajarte el rol a ti mismo te deja fuera de inmediato.
    if user_id == actor:
        if data.is_active is False:
            raise HTTPException(
                status_code=400,
                detail="No puedes desactivar tu propia cuenta",
            )
        if data.role is not None and data.role.value != user.get("role"):
            raise HTTPException(
                status_code=400,
                detail="No puedes cambiar tu propio rol",
            )

    # El tenant nunca puede quedarse sin alguien con acceso completo.
    full_access = ["admin", "supervisor"]
    loses_access = data.is_active is False or (
        data.role is not None and data.role.value not in full_access
    )
    if user.get("role") in full_access and loses_access:
        others = await db[Collections.USERS].count_documents(
            {
                "tenant_id": tenant_id,
                "role": {"$in": full_access},
                "is_active": True,
                "_id": {"$ne": user["_id"]},
            }
        )
        if others == 0:
            raise HTTPException(
                status_code=400,
                detail="Debe quedar al menos un administrador o supervisor activo",
            )

    update: Dict[str, Any] = {"updated_at": now_utc(), "updated_by": actor}
    if data.name is not None:
        update["name"] = data.name
    if data.email is not None and data.email != user.get("email"):
        # El email es la credencial de acceso y es único por tenant.
        taken = await db[Collections.USERS].find_one(
            {"tenant_id": tenant_id, "email": data.email, "_id": {"$ne": user["_id"]}}
        )
        if taken:
            raise HTTPException(
                status_code=409, detail="Ya existe otro usuario con ese email"
            )
        update["email"] = data.email
    if data.password is not None:
        update["password_hash"] = hash_password(data.password)
    if data.role is not None:
        update["role"] = data.role.value
    if data.allowed_warehouse_ids is not None:
        update["allowed_warehouse_ids"] = data.allowed_warehouse_ids
    if data.is_active is not None:
        update["is_active"] = data.is_active

    await db[Collections.USERS].update_one({"_id": user["_id"]}, {"$set": update})
    return await get_user(tenant_id, user_id)
