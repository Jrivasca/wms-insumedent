"""Tenant-scoped data-access layer.

Multi-tenant isolation used to depend on every query author remembering to add
``{"tenant_id": ...}`` by hand. A single forgotten filter leaks data between
companies and no test would notice.

This module centralizes that guarantee. Instead of ``get_database()`` a
request-scoped service acquires ``tenant_db(tenant_id)`` and works with the same
``db[Collections.X]`` API as before, but every filter and every inserted document
is transparently scoped to ``tenant_id``:

    db = tenant_db(user.tenant_id)
    await db[Collections.PRODUCTS].find_one({"sku": sku})   # tenant_id injected
    await db[Collections.PRODUCTS].insert_one({...})        # tenant_id stamped

Forgetting the tenant filter is now harmless — it is added automatically. Trying
to reach another tenant (passing a different ``tenant_id`` in a filter/document,
or a ``$set`` that rewrites it) raises :class:`CrossTenantAccessError` instead of
silently crossing the boundary.

Intentionally NOT wrapped (they operate across tenants or before a tenant is
known, by design): the sync worker's global job poll
(``sync_worker.claim_next_job``), ``auth_service.login`` /
``deps.get_current_user`` (pre-authentication), and ``seed.py`` (bootstrap).
"""
from typing import Any, Dict, Iterable, List, Mapping, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database

# Update operators whose payload could smuggle a different tenant_id in.
_TENANT_WRITE_SECTIONS = ("$set", "$setOnInsert")


class CrossTenantAccessError(RuntimeError):
    """Raised when an operation tries to reach a tenant other than the session's.

    A bug (or attack) rather than a user error: surfaces loudly instead of
    letting the query cross the isolation boundary.
    """


class TenantCollection:
    """A Motor collection bound to a single ``tenant_id``.

    Every read filter and every written document is scoped to that tenant. The
    method surface mirrors the subset of Motor used across the services
    (find/find_one/insert/update/delete/count/aggregate/distinct/
    find_one_and_update); cursors returned by ``find`` are the real Motor
    cursors, so ``.sort().skip().limit().to_list()`` keeps working unchanged.
    """

    __slots__ = ("_collection", "_tenant_id")

    def __init__(self, collection: Any, tenant_id: str) -> None:
        self._collection = collection
        self._tenant_id = tenant_id

    # -- scoping helpers ----------------------------------------------------
    def _scope_filter(self, filter: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        scoped: Dict[str, Any] = dict(filter) if filter else {}
        existing = scoped.get("tenant_id")
        if existing is not None and existing != self._tenant_id:
            raise CrossTenantAccessError(
                f"Query targets tenant_id={existing!r} but the session is bound to "
                f"tenant_id={self._tenant_id!r}"
            )
        scoped["tenant_id"] = self._tenant_id
        return scoped

    def _scope_document(self, document: Mapping[str, Any]) -> Dict[str, Any]:
        doc: Dict[str, Any] = dict(document)
        existing = doc.get("tenant_id")
        if existing is not None and existing != self._tenant_id:
            raise CrossTenantAccessError(
                f"Document carries tenant_id={existing!r} but the session is bound to "
                f"tenant_id={self._tenant_id!r}"
            )
        doc["tenant_id"] = self._tenant_id
        return doc

    def _guard_update(self, update: Any) -> Any:
        """Reject an update that would rewrite ``tenant_id`` to another tenant.

        We do not force-add ``tenant_id`` to ``$set``: on upsert Mongo seeds the
        new document from the (already scoped) filter equality conditions, so the
        tenant is preserved automatically.
        """
        if isinstance(update, Mapping):
            for section in _TENANT_WRITE_SECTIONS:
                payload = update.get(section)
                if isinstance(payload, Mapping) and "tenant_id" in payload:
                    if payload["tenant_id"] != self._tenant_id:
                        raise CrossTenantAccessError(
                            f"Update {section} sets tenant_id={payload['tenant_id']!r} but the "
                            f"session is bound to tenant_id={self._tenant_id!r}"
                        )
        return update

    # -- reads --------------------------------------------------------------
    def find(self, filter: Optional[Mapping[str, Any]] = None, *args: Any, **kwargs: Any):
        return self._collection.find(self._scope_filter(filter), *args, **kwargs)

    async def find_one(self, filter: Optional[Mapping[str, Any]] = None, *args: Any, **kwargs: Any):
        return await self._collection.find_one(self._scope_filter(filter), *args, **kwargs)

    async def count_documents(
        self, filter: Optional[Mapping[str, Any]] = None, *args: Any, **kwargs: Any
    ):
        return await self._collection.count_documents(self._scope_filter(filter), *args, **kwargs)

    async def distinct(self, key: str, filter: Optional[Mapping[str, Any]] = None, **kwargs: Any):
        return await self._collection.distinct(key, self._scope_filter(filter), **kwargs)

    def aggregate(self, pipeline: Iterable[Mapping[str, Any]], *args: Any, **kwargs: Any):
        scoped_pipeline: List[Any] = [{"$match": {"tenant_id": self._tenant_id}}]
        scoped_pipeline.extend(pipeline)
        return self._collection.aggregate(scoped_pipeline, *args, **kwargs)

    # -- writes -------------------------------------------------------------
    async def insert_one(self, document: Mapping[str, Any], *args: Any, **kwargs: Any):
        return await self._collection.insert_one(self._scope_document(document), *args, **kwargs)

    async def insert_many(self, documents: Iterable[Mapping[str, Any]], *args: Any, **kwargs: Any):
        scoped = [self._scope_document(doc) for doc in documents]
        return await self._collection.insert_many(scoped, *args, **kwargs)

    async def update_one(
        self, filter: Mapping[str, Any], update: Any, *args: Any, **kwargs: Any
    ):
        return await self._collection.update_one(
            self._scope_filter(filter), self._guard_update(update), *args, **kwargs
        )

    async def update_many(
        self, filter: Mapping[str, Any], update: Any, *args: Any, **kwargs: Any
    ):
        return await self._collection.update_many(
            self._scope_filter(filter), self._guard_update(update), *args, **kwargs
        )

    async def replace_one(
        self, filter: Mapping[str, Any], replacement: Mapping[str, Any], *args: Any, **kwargs: Any
    ):
        return await self._collection.replace_one(
            self._scope_filter(filter), self._scope_document(replacement), *args, **kwargs
        )

    async def delete_one(self, filter: Mapping[str, Any], *args: Any, **kwargs: Any):
        return await self._collection.delete_one(self._scope_filter(filter), *args, **kwargs)

    async def delete_many(self, filter: Mapping[str, Any], *args: Any, **kwargs: Any):
        return await self._collection.delete_many(self._scope_filter(filter), *args, **kwargs)

    async def find_one_and_update(
        self, filter: Mapping[str, Any], update: Any, *args: Any, **kwargs: Any
    ):
        return await self._collection.find_one_and_update(
            self._scope_filter(filter), self._guard_update(update), *args, **kwargs
        )


class TenantDatabase:
    """A database handle bound to one tenant; ``db[name]`` yields a TenantCollection."""

    __slots__ = ("_db", "_tenant_id")

    def __init__(self, db: AsyncIOMotorDatabase, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required to build a TenantDatabase")
        self._db = db
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def __getitem__(self, name: str) -> TenantCollection:
        return TenantCollection(self._db[name], self._tenant_id)


def tenant_db(tenant_id: str) -> TenantDatabase:
    """Return a tenant-scoped view of the active database.

    Use this in every request-scoped service instead of ``get_database()`` so
    tenant isolation is guaranteed centrally rather than per-query.
    """
    return TenantDatabase(get_database(), tenant_id)
