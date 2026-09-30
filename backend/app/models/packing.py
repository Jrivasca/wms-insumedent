from enum import Enum


class PackingTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    # Cerrada por un supervisor con menos unidades de las pickeadas. Antes quedaba como
    # COMPLETED a secas y la diferencia no se veía en ninguna lista. El picking ya
    # distinguía este caso; el packing no.
    COMPLETED_WITH_DIFFERENCES = "completed_with_differences"
    OBSERVED = "observed"
    CANCELLED = "cancelled"


# Tareas cerradas: no se escanean, no se les crean bultos y no se reinician líneas. Se
# reabren con "Reabrir packing" (supervisor), que revierte el inventario.
CLOSED_PACKING_STATUSES = (
    PackingTaskStatus.COMPLETED.value,
    PackingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
    PackingTaskStatus.CANCELLED.value,
)

# Tareas que cuentan como "empacado" al reconciliar el pedido.
DONE_PACKING_STATUSES = (
    PackingTaskStatus.COMPLETED.value,
    PackingTaskStatus.COMPLETED_WITH_DIFFERENCES.value,
)


class PackingLineStatus(str, Enum):
    PENDING = "pending"
    PACKED = "packed"
    PARTIAL = "partial"
