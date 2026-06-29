from enum import Enum


class BarcodeType(str, Enum):
    EAN13 = "ean13"
    INTERNAL = "internal"
    SUPPLIER = "supplier"
    UNKNOWN = "unknown"


class BarcodeSource(str, Enum):
    DEFONTANA = "defontana"
    MANUAL = "manual"
