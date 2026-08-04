"""Public (unauthenticated) consultation of a bulto by its capability token (QR).

The token is an unguessable per-bulto secret with an expiry (see packing_service).
There is NO login and NO tenant from a JWT: the tenant is derived from the matched
document, and only that one bulto's data (plus its order/dispatch) is returned.
"""
from datetime import timezone

from fastapi import APIRouter, HTTPException

from app.core.database import get_database
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.schemas.public_bulto import PublicBultoDispatch, PublicBultoItem, PublicBultoView

router = APIRouter(prefix="/public", tags=["public"])


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


@router.get("/bultos/{token}", response_model=PublicBultoView)
async def get_bulto_public(token: str) -> PublicBultoView:
    db = get_database()
    task = await db[Collections.PACKING_TASKS].find_one({"packages.public_token": token})
    if not task:
        raise HTTPException(status_code=404, detail="Bulto no encontrado.")

    packages = task.get("packages", [])
    idx = next((i for i, p in enumerate(packages) if p.get("public_token") == token), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Bulto no encontrado.")
    pkg = packages[idx]

    expires = _aware(pkg.get("public_expires_at"))
    if expires and expires < now_utc():
        raise HTTPException(status_code=410, detail="Este enlace ha caducado.")

    tenant_id = task.get("tenant_id")

    # Items only store {sku, quantity}; resolve names via the task lines and aggregate.
    name_by_sku = {ln.get("sku"): ln.get("name") for ln in task.get("lines", [])}
    agg: dict = {}
    for it in pkg.get("items", []):
        sku = it.get("sku")
        if not sku:
            continue
        agg[sku] = agg.get(sku, 0) + (it.get("quantity") or 0)
    items = [PublicBultoItem(sku=sku, name=name_by_sku.get(sku), quantity=qty) for sku, qty in agg.items()]

    # Customer from the order (scoped by the doc's own tenant).
    customer = None
    order = await db[Collections.ORDERS].find_one(
        {"_id": to_object_id(task.get("order_id")), "tenant_id": tenant_id}
    )
    if order:
        customer = order.get("customer")

    # Dispatch info, if the order was already dispatched (best-effort).
    dispatch = PublicBultoDispatch()
    disp = await db[Collections.DISPATCHES].find_one(
        {"tenant_id": tenant_id, "order_id": task.get("order_id")}
    )
    if disp:
        dispatch = PublicBultoDispatch(
            dispatched=True,
            carrier=disp.get("carrier"),
            tracking_number=disp.get("tracking_number"),
            dispatch_date=_iso(disp.get("dispatch_date")),
        )

    return PublicBultoView(
        order_number=task.get("erp_order_number"),
        customer=customer,
        package_label=pkg.get("label") or pkg.get("package_id"),
        package_number=idx + 1,
        package_count=len(packages),
        items=items,
        total_units=sum(agg.values()),
        item_count=len(items),
        packed_at=_iso(task.get("completed_at") or pkg.get("created_at")),
        dispatch=dispatch,
    )
