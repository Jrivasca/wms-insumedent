from typing import List, Optional

from pydantic import BaseModel, Field


class DispatchLineInput(BaseModel):
    """Una línea a despachar en esta guía (split por cantidad)."""

    sku: str
    # Entero y no negativo. El tope (lo empacado menos lo ya despachado) lo valida el
    # servicio, que es el único que conoce el pedido.
    quantity: int = Field(ge=0)


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
    # Clave de idempotencia (la genera la pantalla por formulario abierto): un doble clic no
    # puede emitir dos guías reales en Defontana, cada una con su folio y sin vuelta atrás.
    idempotency_key: Optional[str] = None
