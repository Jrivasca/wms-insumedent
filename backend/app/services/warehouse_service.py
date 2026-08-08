from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.location import DEFAULT_LOCATIONS
from app.schemas.warehouse import LocationCreate, LocationUpdate, WarehouseCreate


async def list_warehouses(tenant_id: str) -> List[Dict[str, Any]]:
    db = get_database()
    cursor = db[Collections.WAREHOUSES].find({"tenant_id": tenant_id}).sort("name", 1)
    return [serialize(w) for w in await cursor.to_list(length=200)]


async def create_warehouse(
    tenant_id: str, data: WarehouseCreate, actor: str, with_defaults: bool = True
) -> Dict[str, Any]:
    db = get_database()
    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "erp_storage_code": data.erp_storage_code,
        "name": data.name,
        "description": data.description,
        "type": data.type.value,
        "sale_available": data.sale_available,
        "is_active": True,
        "raw_erp_data": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    }
    result = await db[Collections.WAREHOUSES].insert_one(doc)
    doc["_id"] = result.inserted_id
    warehouse_id = str(result.inserted_id)

    if with_defaults:
        await _create_default_locations(tenant_id, warehouse_id, actor)

    return serialize(doc)


async def _create_default_locations(tenant_id: str, warehouse_id: str, actor: str) -> None:
    db = get_database()
    now = now_utc()
    for loc in DEFAULT_LOCATIONS:
        existing = await db[Collections.LOCATIONS].find_one(
            {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "code": loc["code"]}
        )
        if existing:
            continue
        await db[Collections.LOCATIONS].insert_one(
            {
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
                "code": loc["code"],
                "name": loc["name"],
                "zone": None,
                "aisle": None,
                "rack": None,
                "level": None,
                "bin": None,
                "type": loc["type"],
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
            }
        )


async def list_locations(
    tenant_id: str, warehouse_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    cursor = db[Collections.LOCATIONS].find(query).sort("code", 1)
    return [serialize(loc) for loc in await cursor.to_list(length=1000)]


async def create_location(
    tenant_id: str, data: LocationCreate, actor: str
) -> Dict[str, Any]:
    db = get_database()
    warehouse = await db[Collections.WAREHOUSES].find_one(
        {"_id": to_object_id(data.warehouse_id), "tenant_id": tenant_id}
    )
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    existing = await db[Collections.LOCATIONS].find_one(
        {"tenant_id": tenant_id, "warehouse_id": data.warehouse_id, "code": data.code}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Location code already exists in warehouse")

    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "warehouse_id": data.warehouse_id,
        "code": data.code,
        "name": data.name or data.code,
        "zone": data.zone,
        "aisle": data.aisle,
        "rack": data.rack,
        "level": data.level,
        "bin": data.bin,
        "type": data.type.value,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
    }
    result = await db[Collections.LOCATIONS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize(doc)


async def update_location(
    tenant_id: str, location_id: str, data: LocationUpdate, actor: str
) -> Dict[str, Any]:
    """Edit a location's fields. The warehouse is fixed; the code stays unique per
    warehouse. Stock/tasks reference the location by id, so renaming code is safe."""
    db = get_database()
    location = await db[Collections.LOCATIONS].find_one(
        {"_id": to_object_id(location_id), "tenant_id": tenant_id}
    )
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    update: Dict[str, Any] = {"updated_at": now_utc(), "updated_by": actor}
    payload = data.model_dump(exclude_unset=True)

    new_code = payload.get("code")
    if new_code is not None:
        new_code = new_code.strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="El código no puede estar vacío")
        if new_code != location["code"]:
            clash = await db[Collections.LOCATIONS].find_one(
                {
                    "tenant_id": tenant_id,
                    "warehouse_id": location["warehouse_id"],
                    "code": new_code,
                    "_id": {"$ne": location["_id"]},
                }
            )
            if clash:
                raise HTTPException(
                    status_code=409, detail="Location code already exists in warehouse"
                )
        update["code"] = new_code

    for field in ("name", "zone", "aisle", "rack", "level", "bin", "is_active"):
        if field in payload:
            update[field] = payload[field]
    if payload.get("type") is not None:
        # LocationType enum -> its string value.
        update["type"] = getattr(payload["type"], "value", payload["type"])

    await db[Collections.LOCATIONS].update_one(
        {"_id": location["_id"]}, {"$set": update}
    )
    return serialize(await db[Collections.LOCATIONS].find_one({"_id": location["_id"]}))
