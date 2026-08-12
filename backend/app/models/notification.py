"""In-app notification model (Phase 1 of docs/notificaciones-diseno.md).

Fan-out storage: one document per recipient (``user_id`` + ``read_at``), so the
"unread for this user" query is a trivial indexed lookup. Emitted by
``notification_service`` from three business events.
"""
from enum import Enum


class NotificationType(str, Enum):
    ORDER_CREATED = "order_created"
    ORDER_DISPATCHED = "order_dispatched"
    STOCK_ZERO = "stock_zero"


# Which roles receive each event. ``admin`` and ``supervisor`` always see
# everything (they have full access); the extra roles are the ones that act on
# that particular event. Configurable per-tenant in a future iteration.
NOTIFICATION_AUDIENCE = {
    NotificationType.ORDER_CREATED.value: {"admin", "supervisor", "picker"},
    NotificationType.ORDER_DISPATCHED.value: {"admin", "supervisor", "sales"},
    NotificationType.STOCK_ZERO.value: {"admin", "supervisor"},
}
