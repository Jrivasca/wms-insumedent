from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database. Connect lazily if needed."""
    global _client, _db
    if _db is None:
        connect()
    return _db


def connect() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        logger.info("Connecting to MongoDB at %s / db=%s", settings.mongodb_uri, settings.mongodb_db)
        _client = AsyncIOMotorClient(settings.mongodb_uri)
        _db = _client[settings.mongodb_db]
    return _db


async def close() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


# Allow tests to inject a database (e.g. mongomock).
def set_database(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


async def ensure_indexes() -> None:
    """Create the indexes required by the WMS at startup (idempotent)."""
    db = get_database()

    await db.users.create_index([("tenant_id", 1), ("email", 1)], unique=True)
    await db.products.create_index([("tenant_id", 1), ("sku", 1)], unique=True)
    await db.barcodes.create_index([("tenant_id", 1), ("barcode", 1)], unique=True)
    await db.warehouses.create_index([("tenant_id", 1), ("erp_storage_code", 1)])
    await db.locations.create_index(
        [("tenant_id", 1), ("warehouse_id", 1), ("code", 1)], unique=True
    )
    await db.inventory_balances.create_index(
        [
            ("tenant_id", 1),
            ("product_id", 1),
            ("warehouse_id", 1),
            ("location_id", 1),
            ("lot_number", 1),
            ("serial_number", 1),
        ],
        unique=True,
    )
    await db.orders.create_index([("tenant_id", 1), ("erp_order_number", 1)], unique=True)
    await db.sync_jobs.create_index([("tenant_id", 1), ("status", 1), ("next_retry_at", 1)])
    await db.audit_logs.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.erp_tokens.create_index([("tenant_id", 1), ("erp", 1)], unique=True)
    await db.erp_connections.create_index([("tenant_id", 1), ("erp", 1)], unique=True)

    logger.info("MongoDB indexes ensured")
