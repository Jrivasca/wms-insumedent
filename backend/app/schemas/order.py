from typing import List, Optional

from pydantic import BaseModel, Field


class OrderLineInput(BaseModel):
    sku: str
    name: Optional[str] = None
    unit: str = "UN"
    # Entero: un pedido de 1.5 unidades no se puede pickear ni empacar, y la pantalla de
    # edición lo dejaba pasar. Los pedidos que llegan del ERP no usan esta ruta.
    ordered_quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    erp_order_number: str
    customer: Optional[str] = None
    lines: List[OrderLineInput]


class OrderUpdate(BaseModel):
    customer: Optional[str] = None
    lines: Optional[List[OrderLineInput]] = None
