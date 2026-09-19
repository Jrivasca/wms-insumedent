"""Programador de sincronizaciones con Defontana (corre en el worker).

Un solo bucle para todas las tareas periódicas, cada una con su cadencia:

- **pedidos**: cada ``DEFONTANA_ORDERS_SYNC_INTERVAL_MINUTES``, solo dentro de
  ``DEFONTANA_ORDERS_SYNC_HOURS`` y (si corresponde) en días hábiles. Es lo urgente: de ahí
  sale el trabajo de bodega.
- **stock**: una vez al día a ``DEFONTANA_STOCK_SYNC_AT``, de madrugada, porque son ~70
  llamadas entre lotes y foto de stock. Si falla, reintenta a la hora siguiente.
- **conciliación**: una vez al día a ``DEFONTANA_RECONCILE_AT``, después de la foto de stock.
  Deja el WMS igual al ERP aplicando solas las diferencias chicas; las grandes quedan para
  revisión humana y se avisa a los supervisores. Exige una foto de menos de 12 horas.

Lo transaccional (recepción, ajuste, despacho) NO pasa por aquí: va por la cola ``sync_jobs``
con reintentos, apenas ocurre la operación.

Cada tarea guarda por empresa su último intento y su último éxito en ``scheduler_runs``, así
sobrevive a los reinicios del worker. Todo apagado por defecto.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.integrations.defontana import order_sync, product_sync, stock_sync
from app.integrations.defontana.schedule import local_now, within_schedule
from app.models import Collections
from app.models.integration import ErpConnectionStatus, ErpProvider
from app.models.notification import NotificationType
from app.services import erp_reconcile_service, notification_service

logger = get_logger("app.workers.defontana_scheduler")

SCHEDULER_ACTOR = "defontana-auto-sync"
LOOP_SECONDS = 60
# Si una tarea diaria falla, se reintenta pasado este tiempo (no al minuto siguiente).
DAILY_RETRY_AFTER = timedelta(hours=1)
ACTIVE_CONNECTION_STATUSES = [
    ErpConnectionStatus.CONFIGURED.value,
    ErpConnectionStatus.CONNECTED.value,
    ErpConnectionStatus.ERROR.value,
]


@dataclass
class Task:
    name: str
    run: Callable[[str], Awaitable[Dict[str, Any]]]
    interval_minutes: Optional[int] = None
    daily_at: Optional[str] = None
    business_hours: bool = False


async def _run_orders(tenant_id: str) -> Dict[str, Any]:
    summary = await order_sync.sync_orders(tenant_id, actor=SCHEDULER_ACTOR)
    await tenant_db(tenant_id)[Collections.ERP_CONNECTIONS].update_one(
        {"erp": ErpProvider.DEFONTANA.value},
        {"$set": {"last_orders_sync_at": now_utc(), "last_orders_sync_summary": summary,
                  "last_orders_sync_error": None}},
    )
    return summary


async def _run_stock(tenant_id: str) -> Dict[str, Any]:
    """Lotes con vencimiento + foto de stock: lo que alimenta el informe y la conciliación."""
    lots = await product_sync.sync_products(tenant_id, SCHEDULER_ACTOR)
    await tenant_db(tenant_id)[Collections.ERP_CONNECTIONS].update_one(
        {"erp": ErpProvider.DEFONTANA.value}, {"$set": {"last_lots_sync_at": now_utc()}}
    )
    stock = await stock_sync.sync_erp_stock(tenant_id, SCHEDULER_ACTOR)
    return {"lots": lots, "stock": stock}


# La conciliación exige una foto fresca: con una vieja "corregiría" el WMS hacia un stock que ya
# no es el de Defontana. Si la foto de la madrugada falló, esta tarea también falla y el
# programador la reintenta a la hora siguiente, hasta que haya foto nueva.
MAX_SNAPSHOT_AGE = timedelta(hours=12)


async def _run_reconcile(tenant_id: str) -> Dict[str, Any]:
    """Conciliación WMS ← Defontana: aplica sola lo chico y avisa si quedó algo para revisar."""
    from datetime import timezone

    taken_at = await erp_reconcile_service.snapshot_taken_at(tenant_id)
    if taken_at is not None and taken_at.tzinfo is None:
        taken_at = taken_at.replace(tzinfo=timezone.utc)
    if taken_at is None or now_utc() - taken_at > MAX_SNAPSHOT_AGE:
        raise RuntimeError(
            f"Sin foto reciente de stock de Defontana (última: {taken_at}); se reintenta más tarde"
        )
    result = await erp_reconcile_service.apply(tenant_id, SCHEDULER_ACTOR)
    if result["pending_review"]:
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.RECONCILE_REVIEW.value,
            title=f"Conciliación: {result['pending_review']} diferencias para revisar",
            body=(
                f"Se aplicaron {result['applied']} ajustes chicos contra Defontana; "
                f"{result['pending_review']} superan el umbral y esperan revisión."
            ),
            entity_type="erp_reconciliation",
            metadata={k: result[k] for k in ("applied", "pending_review", "skipped_blocked")},
        )
    summary = {k: v for k, v in result.items() if k not in ("errors", "snapshot_at")}
    summary["errors"] = len(result["errors"])
    return summary


def tasks() -> List[Task]:
    """Tareas habilitadas según configuración (se relee en cada vuelta)."""
    enabled: List[Task] = []
    if settings.defontana_orders_sync_enabled:
        enabled.append(Task(
            name="orders", run=_run_orders,
            interval_minutes=settings.defontana_orders_sync_interval_minutes,
            business_hours=True,
        ))
    if settings.defontana_stock_sync_enabled:
        enabled.append(Task(name="stock", run=_run_stock, daily_at=settings.defontana_stock_sync_at))
    # Después de la de stock en la lista: si ambas vencen en la misma vuelta (el worker arrancó
    # tarde), la conciliación corre con la foto recién tomada.
    if settings.defontana_reconcile_enabled:
        enabled.append(Task(
            name="reconcile", run=_run_reconcile, daily_at=settings.defontana_reconcile_at
        ))
    return enabled


def _as_local(value: Optional[datetime], reference: datetime) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:  # Motor devuelve naive en UTC
        from datetime import timezone
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(reference.tzinfo)


def is_due(
    task: Task,
    now: datetime,
    last_attempt: Optional[datetime] = None,
    last_success: Optional[datetime] = None,
) -> bool:
    """¿Corresponde correr la tarea ahora? ``now`` y las marcas van en hora local."""
    if task.business_hours and not within_schedule(
        now, settings.defontana_orders_sync_hours, settings.defontana_orders_sync_weekdays_only
    ):
        return False
    last_attempt = _as_local(last_attempt, now)
    last_success = _as_local(last_success, now)

    if task.interval_minutes:
        if last_attempt is None:
            return True
        return now - last_attempt >= timedelta(minutes=task.interval_minutes)

    if task.daily_at:
        try:
            hour, minute = (int(part) for part in task.daily_at.split(":", 1))
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            logger.warning("Hora diaria inválida %r (formato HH:MM); se omite", task.daily_at)
            return False
        if now < scheduled:
            return False
        if last_success is not None and last_success >= scheduled:
            return False  # ya corrió hoy
        if last_attempt is not None and now - last_attempt < DAILY_RETRY_AFTER:
            return False  # falló recién: se reintenta más tarde
        return True

    return False


async def _connections() -> List[Dict[str, Any]]:
    db = get_database()
    return await db[Collections.ERP_CONNECTIONS].find(
        {"erp": ErpProvider.DEFONTANA.value, "status": {"$in": ACTIVE_CONNECTION_STATUSES}}
    ).to_list(length=1000)


async def run_due(now: Optional[datetime] = None) -> Dict[str, int]:
    """Ejecuta las tareas que correspondan, por empresa. Un fallo no frena al resto.
    Devuelve cuántas corridas terminaron bien por tarea."""
    if settings.defontana_mock:
        return {}
    now = now or local_now()
    db = get_database()
    done: Dict[str, int] = {}
    for task in tasks():
        for connection in await _connections():
            tenant_id = connection.get("tenant_id")
            if not tenant_id:
                continue
            state = await db[Collections.SCHEDULER_RUNS].find_one(
                {"task": task.name, "tenant_id": tenant_id}
            ) or {}
            if not is_due(task, now, state.get("last_attempt_at"), state.get("last_success_at")):
                continue
            started = now_utc()
            update: Dict[str, Any] = {"task": task.name, "tenant_id": tenant_id,
                                      "last_attempt_at": started}
            try:
                summary = await task.run(tenant_id)
                update.update({"last_success_at": now_utc(), "last_summary": summary,
                               "last_error": None})
                done[task.name] = done.get(task.name, 0) + 1
                logger.info("tarea %s (tenant %s): %s", task.name, tenant_id, summary)
            except Exception as exc:  # noqa: BLE001 - una empresa no debe frenar al resto
                update["last_error"] = str(exc)[:500]
                logger.warning("tarea %s falló (tenant %s): %s", task.name, tenant_id, exc)
            await db[Collections.SCHEDULER_RUNS].update_one(
                {"task": task.name, "tenant_id": tenant_id}, {"$set": update}, upsert=True
            )
    return done


async def run_forever() -> None:
    if settings.defontana_mock:
        logger.info("Programador Defontana omitido en modo simulado (DEFONTANA_MOCK)")
        return
    if not (settings.defontana_orders_sync_enabled or settings.defontana_stock_sync_enabled
            or settings.defontana_reconcile_enabled):
        logger.info(
            "Programador Defontana sin tareas habilitadas (DEFONTANA_ORDERS_SYNC_ENABLED / "
            "DEFONTANA_STOCK_SYNC_ENABLED / DEFONTANA_RECONCILE_ENABLED)"
        )
        return
    logger.info(
        "Programador Defontana iniciado: pedidos=%s (cada %s min, %s), stock=%s (diario %s), "
        "conciliación=%s (diaria %s, revisión sobre %s u)",
        settings.defontana_orders_sync_enabled, settings.defontana_orders_sync_interval_minutes,
        settings.defontana_orders_sync_hours, settings.defontana_stock_sync_enabled,
        settings.defontana_stock_sync_at, settings.defontana_reconcile_enabled,
        settings.defontana_reconcile_at, settings.defontana_reconcile_review_units,
    )
    while True:
        try:
            await run_due()
        except Exception as exc:  # noqa: BLE001 - mantener vivo el loop
            logger.exception("programador Defontana: %s", exc)
        await asyncio.sleep(LOOP_SECONDS)
