from enum import Enum


class OrderStatus(str, Enum):
    IMPORTED = "imported"
    PENDING_PICKING = "pending_picking"
    PICKING = "picking"
    PICKED = "picked"
    PACKING = "packing"
    PACKED = "packed"
    READY_TO_DISPATCH = "ready_to_dispatch"
    PARTIALLY_DISPATCHED = "partially_dispatched"  # despachado en parte (varias guías)
    DISPATCHED = "dispatched"
    SYNC_ERROR = "sync_error"
    CANCELLED = "cancelled"


class OrderLineStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"  # 0 < fulfilled < ordered (se pickeó/empacó menos de lo pedido)
    PICKED = "picked"
    PACKED = "packed"
    MISSING = "missing"


class OrderFulfillment(str, Enum):
    """Eje ortogonal al pipeline (``status``): indica si el pedido se cumplió al 100%
    o quedó corto por falta de stock. No bloquea el avance del pedido."""

    COMPLETE = "complete"
    PARTIAL = "partial"
