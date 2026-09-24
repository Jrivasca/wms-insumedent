from typing import Any, Dict

from app.integrations.defontana.client import DefontanaConnector


async def dispatch_order(tenant_id: str, order_number: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a dispatch confirmation to Defontana via the connector."""
    connector = DefontanaConnector(tenant_id)
    return await connector.dispatch_order(order_number, payload)


async def dispatch_save(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Emitir la guía de despacho por ``Dispatch/Save`` (B.1: soporta lote/serie)."""
    connector = DefontanaConnector(tenant_id)
    return await connector.dispatch_save(payload)
