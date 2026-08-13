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

    # Operational collections for the picking -> packing -> dispatch flow. These are
    # listed/looked up by tenant + order (and by assignee for the operator queues), so
    # keep tenant_id first like the rest of the compound indexes above.
    await db.picking_tasks.create_index([("tenant_id", 1), ("order_id", 1)])
    await db.picking_tasks.create_index([("tenant_id", 1), ("assigned_to", 1)])
    await db.packing_tasks.create_index([("tenant_id", 1), ("order_id", 1)])
    await db.packing_tasks.create_index([("tenant_id", 1), ("assigned_to", 1)])
    await db.packing_tasks.create_index([("tenant_id", 1), ("picking_task_id", 1)])
    await db.dispatches.create_index([("tenant_id", 1), ("order_id", 1)])

    # The public QR page resolves a bulto by its capability token WITHOUT a tenant
    # (unauthenticated endpoint in routes/public.py: find_one({"packages.public_token": token})).
    # This is intentionally NOT tenant-scoped and is a multikey index over the packages array.
    await db.packing_tasks.create_index([("packages.public_token", 1)])

    # In-app notifications: the feed and the unread badge query by tenant + user,
    # newest first, filtered by read state.
    await db.notifications.create_index(
        [("tenant_id", 1), ("user_id", 1), ("read_at", 1), ("created_at", -1)]
    )
    # Edge-trigger state for stock-zero alerts (dedupe per product+warehouse).
    await db.stock_alerts.create_index(
        [("tenant_id", 1), ("product_id", 1), ("warehouse_id", 1)], unique=True
    )
    # Web Push subscriptions: one row per user+endpoint; looked up by user to push.
    await db.push_subscriptions.create_index(
        [("tenant_id", 1), ("user_id", 1), ("endpoint", 1)], unique=True
    )
    # Folder-watch intake: review queue listed by tenant+status newest-first, and a
    # per-file dedupe log (unique content hash) so a re-synced file is not reprocessed.
    await db.order_import_drafts.create_index(
        [("tenant_id", 1), ("status", 1), ("created_at", -1)]
    )
    await db.intake_runs.create_index([("tenant_id", 1), ("file_hash", 1)], unique=True)
    # Excel catalog import: one state doc per tenant.
    await db.catalog_import_state.create_index([("tenant_id", 1)], unique=True)
    # Near-expiry alerts: dedupe marker per product+warehouse+lot; plus a query on
    # balances by expiration for the periodic scan.
    await db.expiry_alerts.create_index(
        [("tenant_id", 1), ("product_id", 1), ("warehouse_id", 1), ("lot_number", 1)], unique=True
    )
    await db.inventory_balances.create_index([("tenant_id", 1), ("expiration_date", 1)])

    logger.info("MongoDB indexes ensured")
