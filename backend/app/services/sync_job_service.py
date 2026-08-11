from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.sync_job import DEFAULT_MAX_ATTEMPTS, SyncJobStatus


async def enqueue(
    *,
    tenant_id: str,
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
    erp: str = "defontana",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    now = now_utc()
    job = {
        "tenant_id": tenant_id,
        "erp": erp,
        "job_type": job_type,
        "payload": payload or {},
        "status": SyncJobStatus.PENDING.value,
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_retry_at": now,
        "last_error": None,
        "external_document_id": (payload or {}).get("external_document_id"),
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[Collections.SYNC_JOBS].insert_one(job)
    job["_id"] = result.inserted_id
    return serialize(job)


async def list_jobs(
    tenant_id: str, status_filter: Optional[str] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if status_filter:
        query["status"] = status_filter
    cursor = db[Collections.SYNC_JOBS].find(query).sort("created_at", -1).limit(limit)
    return [serialize(j) for j in await cursor.to_list(length=limit)]


async def retry(tenant_id: str, job_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    job = await db[Collections.SYNC_JOBS].find_one(
        {"_id": to_object_id(job_id), "tenant_id": tenant_id}
    )
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    if job["status"] == SyncJobStatus.PROCESSING.value:
        raise HTTPException(status_code=409, detail="Job is currently processing")

    now = now_utc()
    await db[Collections.SYNC_JOBS].update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "status": SyncJobStatus.PENDING.value,
                "next_retry_at": now,
                "last_error": None,
                "updated_at": now,
            }
        },
    )
    return serialize(await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]}))


async def cancel(tenant_id: str, job_id: str) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    job = await db[Collections.SYNC_JOBS].find_one(
        {"_id": to_object_id(job_id), "tenant_id": tenant_id}
    )
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    if job["status"] in (SyncJobStatus.SUCCESS.value, SyncJobStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail="Job cannot be cancelled")

    now = now_utc()
    await db[Collections.SYNC_JOBS].update_one(
        {"_id": job["_id"]},
        {"$set": {"status": SyncJobStatus.CANCELLED.value, "updated_at": now}},
    )
    return serialize(await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]}))
