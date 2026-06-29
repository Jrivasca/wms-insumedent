from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.dispatch import DispatchStatus
from app.models.order import OrderStatus
from app.models.sync_job import SyncJobType
from app.services import sync_job_service


async def list_dispatches(tenant_id: str) -> List[Dict[str, Any]]:
    db = get_database()
    cursor = db[Collections.DISPATCHES].find({"tenant_id": tenant_id}).sort("created_at", -1)
    return [serialize(d) for d in await cursor.to_list(length=500)]


async def get_dispatch(tenant_id: str, dispatch_id: str) -> Dict[str, Any]:
    db = get_database()
    doc = await db[Collections.DISPATCHES].find_one(
        {"_id": to_object_id(dispatch_id), "tenant_id": tenant_id}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    return serialize(doc)


async def confirm_dispatch(
    tenant_id: str,
    order_id: str,
    user: CurrentUser,
    carrier: Optional[str] = None,
    tracking_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Confirm dispatch for a ready order and enqueue the Defontana sync job (8.3)."""
    db = get_database()
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.get("status") != OrderStatus.READY_TO_DISPATCH.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order must be ready_to_dispatch to confirm dispatch",
        )

    # Prevent double dispatch (section 8.3).
    existing = await db[Collections.DISPATCHES].find_one(
        {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": {"$ne": DispatchStatus.ERROR.value},
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Order has already been dispatched"
        )

    now = now_utc()
    dispatch = {
        "tenant_id": tenant_id,
        "order_id": order_id,
        "erp_order_number": order.get("erp_order_number"),
        "status": DispatchStatus.PENDING.value,
        "dispatch_date": now,
        "carrier": carrier,
        "tracking_number": tracking_number,
        "erp_dispatch_response": None,
        "created_by": user.id,
        "updated_by": user.id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.DISPATCHES].insert_one(dispatch)
    dispatch["_id"] = result.inserted_id

    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"status": OrderStatus.DISPATCHED.value, "updated_at": now}},
    )

    # Enqueue the ERP dispatch job; the worker sends it to Defontana asynchronously.
    job = await sync_job_service.enqueue(
        tenant_id=tenant_id,
        job_type=SyncJobType.DISPATCH_ORDER.value,
        payload={
            "dispatch_id": str(dispatch["_id"]),
            "order_id": order_id,
            "erp_order_number": order.get("erp_order_number"),
        },
        created_by=user.id,
    )

    await db[Collections.DISPATCHES].update_one(
        {"_id": dispatch["_id"]}, {"$set": {"sync_job_id": job["id"]}}
    )
    return serialize(await db[Collections.DISPATCHES].find_one({"_id": dispatch["_id"]}))
