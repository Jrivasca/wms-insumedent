from enum import Enum


class LocationType(str, Enum):
    STORAGE = "storage"
    PICKING = "picking"
    STAGING = "staging"
    PACKING = "packing"
    DISPATCH = "dispatch"
    QUARANTINE = "quarantine"
    # Recepción / sin ubicar: stock que ya está en la bodega pero todavía no se guardó en un
    # estante (por ejemplo, lo que trae la conciliación con Defontana). No se pickea desde ahí.
    RECEIVING = "receiving"


# Ubicaciones cuyo stock no se ofrece para pickear: las operativas (ya comprometido con otro
# pedido), cuarentena (bloqueado) y recepción (todavía no ubicado). Fuente única para la
# sugerencia de ubicación del picking y para el aviso de reposición, que antes aplicaban
# reglas distintas.
NON_PICKABLE_LOCATION_TYPES = (
    LocationType.STAGING.value,
    LocationType.PACKING.value,
    LocationType.DISPATCH.value,
    LocationType.QUARANTINE.value,
    LocationType.RECEIVING.value,
)

# Default operational locations created for every new warehouse.
DEFAULT_LOCATIONS = [
    {"code": "STAGING", "name": "Staging", "type": LocationType.STAGING.value},
    {"code": "PACKING", "name": "Packing", "type": LocationType.PACKING.value},
    {"code": "DISPATCH", "name": "Dispatch", "type": LocationType.DISPATCH.value},
    {"code": "QUARANTINE", "name": "Quarantine", "type": LocationType.QUARANTINE.value},
    {"code": "SIN-UBICAR", "name": "Sin ubicar", "type": LocationType.RECEIVING.value},
]
