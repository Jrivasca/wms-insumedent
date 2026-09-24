from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    barcode: str
    quantity: float = Field(default=1, gt=0)
    location_id: Optional[str] = None
    # Lote elegido por el operario (obligatorio para productos que manejan lotes).
    lot_number: Optional[str] = None


class MarkMissingRequest(BaseModel):
    sku: str
    reason: str = Field(min_length=1)


class ResetLineRequest(BaseModel):
    sku: str


class CompletePickingRequest(BaseModel):
    allow_partial: bool = False


class CorrectLotRequest(BaseModel):
    """Corregir el lote mal ingresado de un saldo por el correcto (Parte 3, opción A)."""
    location_id: str
    from_lot_number: Optional[str] = None
    to_lot_number: str = Field(min_length=1)
    to_expiration_date: Optional[datetime] = None
