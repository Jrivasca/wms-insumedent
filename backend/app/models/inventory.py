from enum import Enum


class MovementType(str, Enum):
    RECEIPT = "receipt"
    PICK = "pick"
    PACK = "pack"
    DISPATCH = "dispatch"
    ADJUSTMENT = "adjustment"
    TRANSFER = "transfer"
    COUNT_ADJUSTMENT = "count_adjustment"
    # Ajuste que deja el WMS igual a Defontana. No viaja al ERP: ya tiene esas cantidades.
    RECONCILIATION = "reconciliation"
    # Corrección de la IDENTIDAD del lote de un saldo (lote mal ingresado -> el correcto), sin
    # cambiar la cantidad. No viaja al ERP: Defontana ya manda las cantidades y los lotes.
    LOT_CORRECTION = "lot_correction"


class ReferenceType(str, Enum):
    ORDER = "order"
    PICKING_TASK = "picking_task"
    PACKING_TASK = "packing_task"
    DISPATCH = "dispatch"  # salida por despacho (permite revertir por guía)
    INVENTORY_COUNT = "inventory_count"
    MANUAL = "manual"
    RECONCILIATION = "reconciliation"  # conciliación WMS ← Defontana
