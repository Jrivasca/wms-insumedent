from enum import Enum


class SyncJobType(str, Enum):
    SYNC_PRODUCTS = "sync_products"
    SYNC_WAREHOUSES = "sync_warehouses"
    SYNC_ORDERS = "sync_orders"
    CREATE_INVENTORY_DOCUMENT = "create_inventory_document"
    DISPATCH_ORDER = "dispatch_order"
    CREATE_PRODUCT = "create_product"
    CREATE_ORDER = "create_order"


class SyncJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


DEFAULT_MAX_ATTEMPTS = 5
