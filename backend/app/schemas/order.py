from typing import List, Optional

from pydantic import BaseModel, Field


class OrderLineInput(BaseModel):
    sku: str
    name: Optional[str] = None
    unit: str = "UN"
    ordered_quantity: float = Field(gt=0)


class OrderCreate(BaseModel):
    erp_order_number: str
    customer: Optional[str] = None
    lines: List[OrderLineInput]


class OrderUpdate(BaseModel):
    customer: Optional[str] = None
    lines: Optional[List[OrderLineInput]] = None
