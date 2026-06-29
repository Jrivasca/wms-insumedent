from enum import Enum


class LocationType(str, Enum):
    STORAGE = "storage"
    PICKING = "picking"
    STAGING = "staging"
    PACKING = "packing"
    DISPATCH = "dispatch"
    QUARANTINE = "quarantine"


# Default operational locations created for every new warehouse.
DEFAULT_LOCATIONS = [
    {"code": "STAGING", "name": "Staging", "type": LocationType.STAGING.value},
    {"code": "PACKING", "name": "Packing", "type": LocationType.PACKING.value},
    {"code": "DISPATCH", "name": "Dispatch", "type": LocationType.DISPATCH.value},
    {"code": "QUARANTINE", "name": "Quarantine", "type": LocationType.QUARANTINE.value},
]
