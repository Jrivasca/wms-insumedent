from typing import Optional

from pydantic import BaseModel, Field


class AdjustmentRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str
    # Positive adds stock, negative removes. The resulting movement is recorded.
    quantity: float
    reason: str = Field(min_length=1)
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None


class TransferRequest(BaseModel):
    product_id: str
    warehouse_id: str
    from_location_id: str
    to_location_id: str
    quantity: float = Field(gt=0)
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None


class ReceptionRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str
    quantity: float = Field(gt=0)
    # Optional reference to the inbound document (PO / guía de despacho proveedor).
    reference: Optional[str] = None
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None
    # Whether to push an inventory-entry document to the ERP (default yes).
    sync_erp: bool = True
