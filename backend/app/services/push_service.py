"""Web Push (VAPID) delivery — Phase 2 of docs/notificaciones-diseno.md.

Sits behind the in-app feed: ``notification_service.emit`` writes the feed rows
and then hands the same recipients to :func:`dispatch` here, which pushes to each
browser subscription out-of-band (fire-and-forget) so the business request is
never delayed. Everything is best-effort and tenant/user scoped via ``tenant_db``.

Push is dormant until VAPID keys are configured (``settings.push_enabled``); the
Phase 1 feed keeps working regardless.
"""
import asyncio
import json
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.tenant_db import tenant_db
from app.core.utils import now_utc
from app.models import Collections

logger = get_logger(__name__)

# Keep references to fire-and-forget tasks so they are not garbage-collected.
_BG_TASKS: set = set()


@lru_cache(maxsize=2)
def _vapid_from_pem(pem: str):
    from py_vapid import Vapid02

    return Vapid02.from_pem(pem.encode("utf-8"))


def _send_webpush(subscription_info: Dict[str, Any], data_json: str) -> None:
    """Blocking send via pywebpush. Isolated in one function so tests can
    monkeypatch it without touching the network or needing VAPID keys."""
    from pywebpush import webpush

    webpush(
        subscription_info=subscription_info,
        data=data_json,
        vapid_private_key=_vapid_from_pem(settings.vapid_private_pem),
        vapid_claims={"sub": settings.vapid_subject},
        ttl=600,
    )


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------
async def subscribe(
    tenant_id: str,
    user_id: str,
    endpoint: str,
    keys: Dict[str, str],
    user_agent: Optional[str] = None,
) -> None:
    db = tenant_db(tenant_id)
    now = now_utc()
    await db[Collections.PUSH_SUBSCRIPTIONS].update_one(
        {"user_id": user_id, "endpoint": endpoint},
        {
            "$set": {
                "user_id": user_id,
                "endpoint": endpoint,
                "keys": keys,
                "user_agent": user_agent,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def unsubscribe(tenant_id: str, user_id: str, endpoint: str) -> int:
    db = tenant_db(tenant_id)
    result = await db[Collections.PUSH_SUBSCRIPTIONS].delete_one(
        {"user_id": user_id, "endpoint": endpoint}
    )
    return result.deleted_count


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
async def send_to_users(tenant_id: str, user_ids: List[str], payload: Dict[str, Any]) -> int:
    """Send ``payload`` to every push subscription of ``user_ids``. Dead
    subscriptions (404/410 from the push service) are pruned. Returns the number
    of successful sends. Never raises."""
    if not user_ids:
        return 0
    db = tenant_db(tenant_id)
    data_json = json.dumps(payload)
    sent = 0
    async for sub in db[Collections.PUSH_SUBSCRIPTIONS].find({"user_id": {"$in": list(user_ids)}}):
        info = {"endpoint": sub.get("endpoint"), "keys": sub.get("keys", {})}
        try:
            await asyncio.to_thread(_send_webpush, info, data_json)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - one bad subscription must not stop the rest
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                await db[Collections.PUSH_SUBSCRIPTIONS].delete_one({"_id": sub["_id"]})
                logger.info("pruned expired push subscription (HTTP %s)", code)
            else:
                logger.warning("web push send failed: %s", exc)
    return sent


def dispatch(tenant_id: str, user_ids: List[str], payload: Dict[str, Any]) -> None:
    """Fire-and-forget web push to ``user_ids``. No-op when push is disabled or
    there is no running loop. Does not block the caller."""
    if not settings.push_enabled or not user_ids:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_to_users(tenant_id, list(user_ids), payload))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
