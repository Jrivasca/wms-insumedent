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
    # Folder-watch intake: a parsed PDF needs a human to resolve lines (Fase 1).
    IMPORT_REVIEW = "import_review"
    # Catalog Excel import result / "no lo cargaste en 24 h" reminder (Fase 2).
    CATALOG_IMPORT = "catalog_import"
    # A lot/batch is near its expiration date (Fase 5, FEFO).
    STOCK_EXPIRING = "stock_expiring"
    # Entró stock que permite completar pedidos que quedaron parciales (levantamiento
    # de alertas, Req. 1): el operario los retoma sin esperar aviso del jefe.
    RECEIPT_UNBLOCKS_ORDER = "receipt_unblocks_order"
    # Un envío al ERP agotó sus reintentos: alguien tiene que revisarlo, si no el WMS y
    # Defontana quedan descuadrados en silencio.
    SYNC_JOB_FAILED = "sync_job_failed"
    # Un pedido importado de Defontana se anuló / cerró / despachó allá: se canceló solo en
    # el WMS o, si ya estaba en preparación, requiere revisión de un supervisor.
    ERP_ORDER_CHANGED = "erp_order_changed"


# Which roles receive each event. ``admin`` and ``supervisor`` always see
# everything (they have full access); the extra roles are the ones that act on
# that particular event. Configurable per-tenant in a future iteration.
NOTIFICATION_AUDIENCE = {
    NotificationType.ORDER_CREATED.value: {"admin", "supervisor", "picker"},
    NotificationType.ORDER_DISPATCHED.value: {"admin", "supervisor", "sales"},
    NotificationType.STOCK_ZERO.value: {"admin", "supervisor"},
    NotificationType.IMPORT_REVIEW.value: {"admin", "supervisor", "sales"},
    NotificationType.CATALOG_IMPORT.value: {"admin", "supervisor"},
    NotificationType.STOCK_EXPIRING.value: {"admin", "supervisor"},
    NotificationType.RECEIPT_UNBLOCKS_ORDER.value: {"admin", "supervisor", "picker", "packer"},
    NotificationType.ERP_ORDER_CHANGED.value: {"admin", "supervisor"},
    NotificationType.SYNC_JOB_FAILED.value: {"admin", "supervisor"},
}
