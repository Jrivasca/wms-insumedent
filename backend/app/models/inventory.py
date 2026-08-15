from enum import Enum


class MovementType(str, Enum):
    RECEIPT = "receipt"
    PICK = "pick"
    PACK = "pack"
    DISPATCH = "dispatch"
    ADJUSTMENT = "adjustment"
    TRANSFER = "transfer"
    COUNT_ADJUSTMENT = "count_adjustment"


class ReferenceType(str, Enum):
    ORDER = "order"
    PICKING_TASK = "picking_task"
    PACKING_TASK = "packing_task"
    DISPATCH = "dispatch"  # salida por despacho (permite revertir por guía)
    INVENTORY_COUNT = "inventory_count"
    MANUAL = "manual"
