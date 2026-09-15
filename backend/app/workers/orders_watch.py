"""Sincronización automática de pedidos desde Defontana (flujo 1) — corre en el worker.

Cada ``DEFONTANA_ORDERS_SYNC_INTERVAL_MINUTES``, dentro de ``DEFONTANA_ORDERS_SYNC_HOURS``
(hora de ``DEFONTANA_TIMEZONE``; solo días hábiles si ``DEFONTANA_ORDERS_SYNC_WEEKDAYS_ONLY``),
ejecuta ``order_sync.sync_orders`` para cada empresa con Defontana configurado y deja el
resultado en su ``erp_connections`` (lo muestra la pantalla de configuración). Apagado por
defecto (``DEFONTANA_ORDERS_SYNC_ENABLED=false``) y omitido en modo simulado.
"""
import asyncio

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.integrations.defontana import order_sync
from app.integrations.defontana.schedule import local_now, within_schedule
from app.models import Collections
from app.models.integration import ErpConnectionStatus, ErpProvider

logger = get_logger("app.workers.orders_watch")

AUTO_SYNC_ACTOR = "defontana-auto-sync"
ACTIVE_CONNECTION_STATUSES = [
    ErpConnectionStatus.CONFIGURED.value,
    ErpConnectionStatus.CONNECTED.value,
    ErpConnectionStatus.ERROR.value,
]


async def run_once() -> int:
    """Sincroniza los pedidos de cada empresa con Defontana configurado. Un fallo en una
    empresa no frena al resto. Devuelve cuántas se sincronizaron sin error."""
    db = get_database()
    connections = await db[Collections.ERP_CONNECTIONS].find(
        {"erp": ErpProvider.DEFONTANA.value, "status": {"$in": ACTIVE_CONNECTION_STATUSES}}
    ).to_list(length=1000)
    ok = 0
    for conn in connections:
        tenant_id = conn.get("tenant_id")
        if not tenant_id:
            continue
        now = now_utc()
        try:
            summary = await order_sync.sync_orders(tenant_id, actor=AUTO_SYNC_ACTOR)
            update = {
                "last_orders_sync_at": now,
                "last_orders_sync_summary": summary,
                "last_orders_sync_error": None,
            }
            ok += 1
            if summary.get("created") or summary.get("cancelled") or summary.get("flagged"):
                logger.info("orders watch tenant %s: %s", tenant_id, summary)
        except Exception as exc:  # noqa: BLE001 - una empresa no debe frenar al resto
            logger.warning("orders watch falló para tenant %s: %s", tenant_id, exc)
            update = {"last_orders_sync_at": now, "last_orders_sync_error": str(exc)[:500]}
        await tenant_db(tenant_id)[Collections.ERP_CONNECTIONS].update_one(
            {"erp": ErpProvider.DEFONTANA.value}, {"$set": update}
        )
    return ok


async def run_forever() -> None:
    if not settings.defontana_orders_sync_enabled:
        logger.info("Sync automático de pedidos Defontana deshabilitado (DEFONTANA_ORDERS_SYNC_ENABLED)")
        return
    if settings.defontana_mock:
        logger.info("Sync automático de pedidos Defontana omitido en modo simulado (DEFONTANA_MOCK)")
        return
    interval = max(60, settings.defontana_orders_sync_interval_minutes * 60)
    logger.info(
        "Sync automático de pedidos Defontana iniciado (cada %ss, horario %s, solo días hábiles=%s)",
        interval, settings.defontana_orders_sync_hours, settings.defontana_orders_sync_weekdays_only,
    )
    while True:
        try:
            if within_schedule(
                local_now(),
                settings.defontana_orders_sync_hours,
                settings.defontana_orders_sync_weekdays_only,
            ):
                await run_once()
        except Exception as exc:  # noqa: BLE001 - mantener vivo el loop
            logger.exception("orders watch loop error: %s", exc)
        await asyncio.sleep(interval)
