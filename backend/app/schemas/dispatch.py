from typing import List, Optional

from pydantic import BaseModel


class DispatchLineInput(BaseModel):
    """Una línea a despachar en esta guía (split por cantidad)."""

    sku: str
    quantity: int


class DispatchRequest(BaseModel):
    # Guía de despacho: por ahora se ingresa a mano (fase futura: crearla en Defontana
    # y traer el folio). Opcional. El envío (transportista/tracking) también es opcional.
    guide_number: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    # Despacho DIVIDIDO (opcional). Si ambos son None se despacha todo el remanente
    # (packed - dispatched) del pedido, como antes.
    package_ids: Optional[List[str]] = None  # despachar bultos específicos en esta guía
    lines: Optional[List[DispatchLineInput]] = None  # o cantidades por SKU
