"""Synchronization worker (section 11).

Uses MongoDB as a simple queue (no Celery). Picks up pending/retrying ``sync_jobs``,
marks them ``processing``, runs the matching ERP operation, and records the result.
On failure it increments ``attempts`` and reschedules with exponential backoff until
``max_attempts`` is exceeded, after which the job is marked ``failed``.
"""
import asyncio
from datetime import timedelta
from typing import Any, Dict, Optional

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.core.logging import configure_logging, get_logger
from app.core.utils import now_utc, to_object_id
from app.models import Collections
from app.models.dispatch import DispatchStatus
from app.models.sync_job import SyncJobStatus, SyncJobType
from app.integrations.defontana import (
    dispatch_sync,
    inventory_sync,
    order_sync,
    product_sync,
    warehouse_sync,
)
from app.integrations.defontana.client import DefontanaConnector

logger = get_logger("app.workers.sync_worker")

POLL_INTERVAL_SECONDS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 600


async def claim_next_job() -> Optional[Dict[str, Any]]:
    db = get_database()
    now = now_utc()
    return await db[Collections.SYNC_JOBS].find_one_and_update(
        {
            "status": {"$in": [SyncJobStatus.PENDING.value, SyncJobStatus.RETRYING.value]},
            "next_retry_at": {"$lte": now},
        },
        {"$set": {"status": SyncJobStatus.PROCESSING.value, "updated_at": now}},
        sort=[("next_retry_at", 1)],
        return_document=True,
    )


async def _handle_dispatch_order(job: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = job["tenant_id"]
    db = tenant_db(tenant_id)
    payload = job.get("payload", {})
    dispatch_id = payload.get("dispatch_id")

    order_number = int(payload.get("erp_order_number") or 0)
    response = await dispatch_sync.dispatch_order(
        tenant_id,
        order_number,
        {"tracking_number": payload.get("tracking_number")},
    )

    if dispatch_id:
        await db[Collections.DISPATCHES].update_one(
            {"_id": to_object_id(dispatch_id), "tenant_id": tenant_id},
            {
                "$set": {
                    "status": DispatchStatus.COMPLETED.value,
                    "erp_dispatch_response": response,
                    "updated_at": now_utc(),
                }
            },
        )
    return {"external_document_id": response.get("DispatchGuide"), "response": response}


async def _handle_create_inventory_document(job: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = job["tenant_id"]
    payload = job.get("payload", {})
    result = await inventory_sync.create_inventory_document(tenant_id, payload)
    response = result.get("response", {})
    return {
        "external_document_id": payload.get("externalDocumentID"),
        "response": response,
    }


async def _handle_create_product(job: Dict[str, Any]) -> Dict[str, Any]:
    connector = DefontanaConnector(job["tenant_id"])
    payload = job.get("payload", {})
    response = await connector.create_product(payload)
    return {"external_document_id": str(response.get("Code") or payload.get("Code")), "response": response}


async def _handle_create_order(job: Dict[str, Any]) -> Dict[str, Any]:
    connector = DefontanaConnector(job["tenant_id"])
    payload = job.get("payload", {})
    response = await connector.create_order(payload)
    return {"external_document_id": str(response.get("Number") or payload.get("Number")), "response": response}


async def _handle_sync_products(job: Dict[str, Any]) -> Dict[str, Any]:
    return await product_sync.sync_products(job["tenant_id"])


async def _handle_sync_warehouses(job: Dict[str, Any]) -> Dict[str, Any]:
    return await warehouse_sync.sync_warehouses(job["tenant_id"])


async def _handle_sync_orders(job: Dict[str, Any]) -> Dict[str, Any]:
    return await order_sync.sync_orders(job["tenant_id"])


HANDLERS = {
    SyncJobType.DISPATCH_ORDER.value: _handle_dispatch_order,
    SyncJobType.CREATE_INVENTORY_DOCUMENT.value: _handle_create_inventory_document,
    SyncJobType.CREATE_PRODUCT.value: _handle_create_product,
    SyncJobType.CREATE_ORDER.value: _handle_create_order,
    SyncJobType.SYNC_PRODUCTS.value: _handle_sync_products,
    SyncJobType.SYNC_WAREHOUSES.value: _handle_sync_warehouses,
    SyncJobType.SYNC_ORDERS.value: _handle_sync_orders,
}


async def process_job(job: Dict[str, Any]) -> None:
    db = get_database()
    job_type = job.get("job_type")
    handler = HANDLERS.get(job_type)
    now = now_utc()

    if handler is None:
        await db[Collections.SYNC_JOBS].update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": SyncJobStatus.FAILED.value,
                    "last_error": f"Unknown job_type '{job_type}'",
                    "updated_at": now,
                }
            },
        )
        return

    try:
        result = await handler(job)
        await db[Collections.SYNC_JOBS].update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": SyncJobStatus.SUCCESS.value,
                    "last_error": None,
                    "external_document_id": result.get("external_document_id"),
                    "result": result,
                    "updated_at": now_utc(),
                }
            },
        )
        logger.info("Job %s (%s) completed", job["_id"], job_type)
    except Exception as exc:  # noqa: BLE001 - record and reschedule any failure
        attempts = job.get("attempts", 0) + 1
        max_attempts = job.get("max_attempts", 5)
        update: Dict[str, Any] = {
            "attempts": attempts,
            "last_error": str(exc),
            "updated_at": now_utc(),
        }
        if attempts < max_attempts:
            backoff = min(BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)), BACKOFF_MAX_SECONDS)
            update["status"] = SyncJobStatus.RETRYING.value
            update["next_retry_at"] = now_utc() + timedelta(seconds=backoff)
            logger.warning(
                "Job %s (%s) failed (attempt %s/%s); retrying in %ss: %s",
                job["_id"], job_type, attempts, max_attempts, backoff, exc,
            )
        else:
            update["status"] = SyncJobStatus.FAILED.value
            logger.error(
                "Job %s (%s) failed permanently after %s attempts: %s",
                job["_id"], job_type, attempts, exc,
            )
        await db[Collections.SYNC_JOBS].update_one({"_id": job["_id"]}, {"$set": update})


async def run_forever() -> None:
    logger.info("Sync worker started (poll every %ss)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            job = await claim_next_job()
            if job is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            await process_job(job)
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            logger.exception("Worker loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _run_all() -> None:
    """Run the ERP sync-job drain, the folder-watch intake and the near-expiry watch."""
    from app.workers import expiry_watch, folder_intake

    await asyncio.gather(
        run_forever(), folder_intake.run_forever(), expiry_watch.run_forever()
    )


def main() -> None:
    configure_logging()
    asyncio.run(_run_all())


if __name__ == "__main__":
    main()
