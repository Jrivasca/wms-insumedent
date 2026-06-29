from enum import Enum


class OrderStatus(str, Enum):
    IMPORTED = "imported"
    PENDING_PICKING = "pending_picking"
    PICKING = "picking"
    PICKED = "picked"
    PACKING = "packing"
    PACKED = "packed"
    READY_TO_DISPATCH = "ready_to_dispatch"
    DISPATCHED = "dispatched"
    SYNC_ERROR = "sync_error"
    CANCELLED = "cancelled"


class OrderLineStatus(str, Enum):
    PENDING = "pending"
    PICKED = "picked"
    PACKED = "packed"
    MISSING = "missing"
