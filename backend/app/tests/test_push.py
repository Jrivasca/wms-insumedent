"""Web Push (Phase 2): subscription CRUD, delivery fan-out, dead-subscription
pruning, and tenant/user scoping. pywebpush itself is monkeypatched, so these run
without VAPID keys or network."""
import pytest

from app.core.database import get_database
from app.core.tenant_db import tenant_db
from app.models import Collections
from app.services import push_service

pytestmark = pytest.mark.asyncio

SUB = {"p256dh": "key-p", "auth": "key-a"}


async def _tenant(name: str) -> str:
    db = get_database()
    r = await db[Collections.TENANTS].insert_one({"name": name, "is_active": True})
    return str(r.inserted_id)


async def _count_subs(tenant_id: str) -> int:
    return await tenant_db(tenant_id)[Collections.PUSH_SUBSCRIPTIONS].count_documents({})


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _PushError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.response = _Resp(status_code)


# ---------------------------------------------------------------------------
# subscription CRUD
# ---------------------------------------------------------------------------
async def test_subscribe_is_idempotent_per_endpoint():
    a = await _tenant("A")
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)  # same endpoint -> upsert
    await push_service.subscribe(a, "u1", "https://push/e2", SUB)  # new device
    assert await _count_subs(a) == 2


async def test_unsubscribe_removes_only_that_endpoint():
    a = await _tenant("A")
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)
    await push_service.subscribe(a, "u1", "https://push/e2", SUB)
    removed = await push_service.unsubscribe(a, "u1", "https://push/e1")
    assert removed == 1
    assert await _count_subs(a) == 1


# ---------------------------------------------------------------------------
# delivery
# ---------------------------------------------------------------------------
async def test_send_to_users_pushes_to_each_subscription(monkeypatch):
    a = await _tenant("A")
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)
    await push_service.subscribe(a, "u1", "https://push/e2", SUB)
    await push_service.subscribe(a, "u2", "https://push/e3", SUB)

    calls = []
    monkeypatch.setattr(push_service, "_send_webpush", lambda info, data: calls.append(info["endpoint"]))

    sent = await push_service.send_to_users(a, ["u1"], {"title": "t", "body": "b"})
    assert sent == 2
    assert set(calls) == {"https://push/e1", "https://push/e2"}  # only u1's devices


async def test_send_prunes_dead_subscriptions(monkeypatch):
    a = await _tenant("A")
    await push_service.subscribe(a, "u1", "https://push/gone", SUB)

    def boom(info, data):
        raise _PushError(410)

    monkeypatch.setattr(push_service, "_send_webpush", boom)
    sent = await push_service.send_to_users(a, ["u1"], {"title": "t", "body": "b"})
    assert sent == 0
    assert await _count_subs(a) == 0  # 410 -> pruned


async def test_send_keeps_subscription_on_transient_error(monkeypatch):
    a = await _tenant("A")
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)

    def boom(info, data):
        raise _PushError(500)

    monkeypatch.setattr(push_service, "_send_webpush", boom)
    sent = await push_service.send_to_users(a, ["u1"], {"title": "t", "body": "b"})
    assert sent == 0
    assert await _count_subs(a) == 1  # 500 is transient -> kept


async def test_subscriptions_are_tenant_isolated(monkeypatch):
    a = await _tenant("A")
    b = await _tenant("B")
    await push_service.subscribe(a, "u1", "https://push/e1", SUB)

    calls = []
    monkeypatch.setattr(push_service, "_send_webpush", lambda info, data: calls.append(info))

    # Tenant B cannot reach tenant A's subscription for the same user id.
    assert await push_service.send_to_users(b, ["u1"], {"title": "t", "body": "b"}) == 0
    assert calls == []
    assert await push_service.send_to_users(a, ["u1"], {"title": "t", "body": "b"}) == 1
