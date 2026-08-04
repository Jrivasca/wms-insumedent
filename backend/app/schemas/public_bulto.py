"""Public (token-gated) view of a bulto, returned to the QR consultation page."""
from typing import List, Optional

from pydantic import BaseModel


class PublicBultoItem(BaseModel):
    sku: str
    name: Optional[str] = None
    quantity: float


class PublicBultoDispatch(BaseModel):
    dispatched: bool = False
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    dispatch_date: Optional[str] = None


class PublicBultoView(BaseModel):
    order_number: Optional[str] = None
    customer: Optional[str] = None
    package_label: Optional[str] = None
    package_number: int
    package_count: int
    items: List[PublicBultoItem]
    total_units: float
    item_count: int
    packed_at: Optional[str] = None
    dispatch: PublicBultoDispatch
