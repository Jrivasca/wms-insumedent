from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.dispatch import DispatchStatus
from app.models.order import OrderStatus
from app.models.sync_job import SyncJobType
from app.services import sync_job_service


async def list_dispatches(
    tenant_id: str, limit: int = 500, offset: int = 0
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    total = await db[Collections.DISPATCHES].count_documents(query)
    cursor = (
        db[Collections.DISPATCHES].find(query).sort("created_at", -1).skip(offset).limit(limit)
    )
    items = [serialize(d) for d in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def get_dispatch(tenant_id: str, dispatch_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
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
    guide_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Confirm dispatch for a ready order and enqueue the Defontana sync job (8.3)."""
    db = tenant_db(tenant_id)
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

    # Prevent double dispatch (8.3). A cancelled/errored dispatch does not count, so an
    # order whose dispatch was annulled can be dispatched again.
    existing = await db[Collections.DISPATCHES].find_one(
        {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": {"$nin": [DispatchStatus.ERROR.value, DispatchStatus.CANCELLED.value]},
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
        "guide_number": guide_number,
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


async def cancel_dispatch(tenant_id: str, order_id: str, user: CurrentUser) -> Dict[str, Any]:
    """Retroceso: anular el despacho de un pedido despachado. El pedido vuelve a
    'ready_to_dispatch' y el despacho queda 'cancelled' (puede re-despacharse)."""
    db = tenant_db(tenant_id)
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(order_id), "tenant_id": tenant_id}
    )
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.get("status") != OrderStatus.DISPATCHED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede anular el despacho de un pedido despachado.",
        )

    now = now_utc()
    dispatch = await db[Collections.DISPATCHES].find_one(
        {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": {"$nin": [DispatchStatus.ERROR.value, DispatchStatus.CANCELLED.value]},
        }
    )
    if dispatch:
        await db[Collections.DISPATCHES].update_one(
            {"_id": dispatch["_id"]},
            {"$set": {"status": DispatchStatus.CANCELLED.value, "updated_at": now,
                      "updated_by": user.id}},
        )
    await db[Collections.ORDERS].update_one(
        {"_id": order["_id"]},
        {"$set": {"status": OrderStatus.READY_TO_DISPATCH.value, "updated_at": now}},
    )
    return await get_dispatch(tenant_id, str(dispatch["_id"])) if dispatch else {"status": "reverted"}
