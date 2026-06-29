from typing import Optional

from pydantic import BaseModel

from app.models.product import BarcodeType


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    unit: str = "UN"
    brand: Optional[str] = None
    category: Optional[str] = None
    uses_lots: bool = False
    uses_serials: bool = False
    is_service: bool = False


class BarcodeCreate(BaseModel):
    barcode: str
    type: BarcodeType = BarcodeType.INTERNAL
