from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator

# El motivo de un ajuste queda en la trazabilidad y en la glosa que viaja al ERP: un texto
# de solo espacios no explica nada, así que se recorta ANTES de exigir largo mínimo.
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Las cantidades de bodega se cuentan en unidades enteras. Aceptar 1.5 dejaba saldos y
# movimientos fraccionarios que ni el ERP ni las etiquetas saben representar.
PositiveUnits = Annotated[int, Field(gt=0)]


class AdjustmentRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str
    # Positive adds stock, negative removes. The resulting movement is recorded.
    quantity: int
    reason: ReasonText
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def _no_cero(cls, v: int) -> int:
        # Un ajuste de 0 no cambia nada pero deja un movimiento y una alerta al supervisor:
        # es ruido puro en la trazabilidad.
        if v == 0:
            raise ValueError("La cantidad del ajuste no puede ser 0")
        return v


class TransferRequest(BaseModel):
    product_id: str
    warehouse_id: str
    from_location_id: str
    to_location_id: str
    quantity: PositiveUnits
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None


class PutawayRequest(BaseModel):
    """Ubicar stock: mover un saldo exacto (con su lote, serie y vencimiento) a otra
    ubicación de la misma bodega."""
    balance_id: str
    to_location_id: str
    quantity: float = Field(gt=0)


class ReceptionRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str
    quantity: PositiveUnits
    # Optional reference to the inbound document (PO / guía de despacho proveedor).
    reference: Optional[str] = None
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None
    # Fecha de vencimiento del lote recibido (Fase 5, FEFO + alertas). "YYYY-MM-DD".
    expiration_date: Optional[datetime] = None
    # Recibir mercadería ya vencida es casi siempre un error de tipeo en la fecha, así que
    # se rechaza salvo que el operario lo confirme explícitamente (hay casos reales: una
    # devolución que entra a cuarentena).
    allow_expired: bool = False
    # Whether to push an inventory-entry document to the ERP (default yes).
    sync_erp: bool = True
