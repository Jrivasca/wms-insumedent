from typing import Optional

from pydantic import BaseModel, Field


class PackScanRequest(BaseModel):
    barcode: str
    quantity: float = Field(default=1, gt=0)
    package_id: Optional[str] = None


class CreatePackageRequest(BaseModel):
    label: Optional[str] = None


class ResetLineRequest(BaseModel):
    sku: str
