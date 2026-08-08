from typing import Optional

from pydantic import BaseModel


class DispatchRequest(BaseModel):
    # Guía de despacho: por ahora se ingresa a mano (fase futura: crearla en Defontana
    # y traer el folio). Opcional. El envío (transportista/tracking) también es opcional.
    guide_number: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
