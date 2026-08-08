"""Aggregated KPIs for the operational dashboard.

Everything is counted server-side (count_documents / distinct) so the numbers are
exact and not capped by any list page size. The shape mirrors ``DashboardStats`` in
the web app.
"""
from typing import Any, Dict

from app.core.database import get_database
from app.core.utils import now_utc
from app.models import Collections
from app.models.order import OrderStatus
from app.models.packing import PackingTaskStatus
from app.models.picking import PickingTaskStatus
from app.models.sync_job import SyncJobStatus


async def get_stats(tenant_id: str) -> Dict[str, Any]:
    db = get_database()

    def q(**extra: Any) -> Dict[str, Any]:
        return {"tenant_id": tenant_id, **extra}

    orders = db[Collections.ORDERS]

    # --- Orders: full breakdown by status + business groupings -------------
    by_status: Dict[str, int] = {}
    for st in OrderStatus:
        by_status[st.value] = await orders.count_documents(q(status=st.value))
    total_orders = await orders.count_documents(q())

    def grp(*statuses: str) -> int:
        return sum(by_status.get(s, 0) for s in statuses)

    por_procesar = grp(OrderStatus.IMPORTED.value, OrderStatus.PENDING_PICKING.value)
    en_proceso = grp(
        OrderStatus.PICKING.value,
        OrderStatus.PICKED.value,
        OrderStatus.PACKING.value,
        OrderStatus.PACKED.value,
    )
    listos = by_status.get(OrderStatus.READY_TO_DISPATCH.value, 0)
    despachados = by_status.get(OrderStatus.DISPATCHED.value, 0)
    error_cancelados = grp(OrderStatus.SYNC_ERROR.value, OrderStatus.CANCELLED.value)

    start_today = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    despachados_hoy = await db[Collections.DISPATCHES].count_documents(
        q(dispatch_date={"$gte": start_today})
    )

    # --- Inventory / products ---------------------------------------------
    productos = await db[Collections.PRODUCTS].count_documents(q())
    # "Sin stock" only makes sense for physical products (services never hold stock).
    productos_fisicos = await db[Collections.PRODUCTS].count_documents(
        q(is_service={"$ne": True})
    )
    con_stock_ids = await db[Collections.INVENTORY_BALANCES].distinct(
        "product_id", q(quantity_available={"$gt": 0})
    )
    con_stock = len(con_stock_ids)
    sin_stock = max(productos_fisicos - con_stock, 0)
    ubicaciones = await db[Collections.LOCATIONS].count_documents(q(is_active={"$ne": False}))

    # --- Operational work in flight ---------------------------------------
    picking_abiertas = await db[Collections.PICKING_TASKS].count_documents(
        q(status={"$in": [
            PickingTaskStatus.PENDING.value,
            PickingTaskStatus.IN_PROGRESS.value,
            PickingTaskStatus.PAUSED.value,
        ]})
    )
    packing_abiertas = await db[Collections.PACKING_TASKS].count_documents(
        q(status={"$in": [
            PackingTaskStatus.PENDING.value,
            PackingTaskStatus.IN_PROGRESS.value,
        ]})
    )
    sync_pendientes = await db[Collections.SYNC_JOBS].count_documents(
        q(status={"$in": [
            SyncJobStatus.PENDING.value,
            SyncJobStatus.PROCESSING.value,
            SyncJobStatus.RETRYING.value,
        ]})
    )

    return {
        "orders": {
            "total": total_orders,
            "por_procesar": por_procesar,
            "en_proceso": en_proceso,
            "listos_despacho": listos,
            "despachados": despachados,
            "despachados_hoy": despachados_hoy,
            "error_cancelados": error_cancelados,
            "por_estado": by_status,
        },
        "inventory": {
            "productos": productos,
            "sin_stock": sin_stock,
            "con_stock": con_stock,
            "ubicaciones": ubicaciones,
        },
        "operations": {
            "picking_abiertas": picking_abiertas,
            "packing_abiertas": packing_abiertas,
            "sync_pendientes": sync_pendientes,
        },
    }
