from typing import Optional

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    barcode: str
    quantity: float = Field(default=1, gt=0)
    location_id: Optional[str] = None


class MarkMissingRequest(BaseModel):
    sku: str
    reason: str = Field(min_length=1)


class ResetLineRequest(BaseModel):
    sku: str


class CompletePickingRequest(BaseModel):
    allow_partial: bool = False
