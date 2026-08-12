"""In-app notifications (Phase 1: feed).

``emit`` fans an event out to every recipient (one document per user) and never
raises — a notification failure must never break the business operation that
triggered it. The read helpers are tenant + user scoped, so a user only ever
sees and marks their own notifications.
"""
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc, page, serialize, to_object_id
from app.models import Collections
from app.models.notification import NOTIFICATION_AUDIENCE
from app.services import push_service

logger = get_logger(__name__)


def _entity_url(entity_type: Optional[str], entity_id: Optional[str]) -> str:
    """Where a notification points in the web app (the order list has no per-id page)."""
    if entity_type == "product" and entity_id:
        return f"/products/{entity_id}"
    if entity_type == "order":
        return "/orders"
    return "/"


async def _recipient_ids(db, roles: set, exclude_id: Optional[str]) -> List[str]:
    """Active users of the tenant whose role is in ``roles`` (minus the actor)."""
    if not roles:
        return []
    cursor = db[Collections.USERS].find(
        {"role": {"$in": list(roles)}, "is_active": {"$ne": False}}
    )
    ids = [str(u["_id"]) async for u in cursor]
    return [uid for uid in ids if uid != exclude_id]


async def emit(
    *,
    tenant_id: str,
    notification_type: str,
    title: str,
    body: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    actor_id: Optional[str] = None,
) -> int:
    """Fan ``notification_type`` out to its audience. Returns how many rows were
    written. Best-effort: any failure is logged and swallowed."""
    try:
        roles = NOTIFICATION_AUDIENCE.get(notification_type, set())
        db = tenant_db(tenant_id)
        recipients = await _recipient_ids(db, roles, actor_id)
        if not recipients:
            return 0
        now = now_utc()
        docs = [
            {
                "tenant_id": tenant_id,
                "user_id": uid,
                "type": notification_type,
                "title": title,
                "body": body,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
                "read_at": None,
                "created_at": now,
                "created_by": actor_id or "system",
            }
            for uid in recipients
        ]
        await db[Collections.NOTIFICATIONS].insert_many(docs)
        # Phase 2: also push to the browser (fire-and-forget; no-op if disabled).
        push_service.dispatch(
            tenant_id,
            recipients,
            {
                "title": title,
                "body": body,
                "url": _entity_url(entity_type, entity_id),
                "tag": notification_type,
            },
        )
        return len(docs)
    except Exception as exc:  # noqa: BLE001 - notifications must never break the caller
        logger.warning("notification emit failed (%s): %s", notification_type, exc)
        return 0


async def list_for_user(
    tenant_id: str,
    user_id: str,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    db = tenant_db(tenant_id)
    query: Dict[str, Any] = {"user_id": user_id}
    if unread_only:
        query["read_at"] = None
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total = await db[Collections.NOTIFICATIONS].count_documents(query)
    cursor = (
        db[Collections.NOTIFICATIONS]
        .find(query)
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    items = [serialize(n) for n in await cursor.to_list(length=limit)]
    return page(items, total, limit, offset)


async def unread_count(tenant_id: str, user_id: str) -> int:
    db = tenant_db(tenant_id)
    return await db[Collections.NOTIFICATIONS].count_documents(
        {"user_id": user_id, "read_at": None}
    )


async def mark_read(tenant_id: str, user_id: str, notification_id: str) -> int:
    db = tenant_db(tenant_id)
    result = await db[Collections.NOTIFICATIONS].update_one(
        {"_id": to_object_id(notification_id), "user_id": user_id, "read_at": None},
        {"$set": {"read_at": now_utc()}},
    )
    return result.modified_count


async def mark_all_read(tenant_id: str, user_id: str) -> int:
    db = tenant_db(tenant_id)
    result = await db[Collections.NOTIFICATIONS].update_many(
        {"user_id": user_id, "read_at": None},
        {"$set": {"read_at": now_utc()}},
    )
    return result.modified_count
