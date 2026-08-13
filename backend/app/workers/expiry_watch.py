"""Near-expiry watch (Plan 1, Fase 5) — runs inside the worker container.

Every ``EXPIRY_CHECK_INTERVAL_SECONDS`` it scans each tenant's stock for lots that
expire within ``EXPIRY_ALERT_DAYS`` (and still have quantity) and emits a
``stock_expiring`` notification, deduped per lot. Always on (independent of the
folder-watch), since it's about inventory, not files.
"""
import asyncio

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.models import Collections
from app.services import inventory_service

logger = get_logger("app.workers.expiry_watch")


async def _run_once() -> None:
    db = get_database()
    tenants = await db[Collections.TENANTS].find({}).to_list(length=1000)
    total = 0
    for tenant in tenants:
        tenant_id = str(tenant["_id"])
        try:
            total += await inventory_service.check_expiring_stock(tenant_id)
        except Exception as exc:  # noqa: BLE001 - un tenant no debe frenar al resto
            logger.warning("expiry check falló para tenant %s: %s", tenant_id, exc)
    if total:
        logger.info("expiry watch: %s alerta(s) de vencimiento", total)


async def run_forever() -> None:
    interval = max(300, settings.expiry_check_interval_seconds)
    logger.info(
        "Expiry watch iniciado (cada %ss, ventana %s d)", interval, settings.expiry_alert_days
    )
    while True:
        try:
            await _run_once()
        except Exception as exc:  # noqa: BLE001 - mantener vivo el loop
            logger.exception("expiry watch loop error: %s", exc)
        await asyncio.sleep(interval)
