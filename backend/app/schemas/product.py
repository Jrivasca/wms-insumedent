from typing import Optional

from pydantic import BaseModel, Field

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
    # Optional extras created together with the product.
    barcode: Optional[str] = None
    # Un precio negativo no existe y ensucia la valorización que viaja al ERP en los
    # documentos de inventario (``price`` de cada línea).
    cost: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)


class BarcodeCreate(BaseModel):
    barcode: str
    type: BarcodeType = BarcodeType.INTERNAL
