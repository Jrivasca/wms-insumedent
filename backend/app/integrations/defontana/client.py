"""Defontana ERP connector (real HTTPX client + mock mode).

When ``DEFONTANA_MOCK=true`` the connector returns simulated data and performs no
network calls. Mock responses are explicitly flagged with ``"mock": true`` so a
simulated success can never be mistaken for a real one (section 18).
"""
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.models import Collections
from app.integrations.erp_connector import ERPConnector
from app.integrations.defontana import mock_data
from app.integrations.defontana.token_manager import DefontanaTokenManager

logger = get_logger(__name__)


class DefontanaConnector(ERPConnector):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.token_manager = DefontanaTokenManager()
        self.mock = settings.defontana_mock

    async def _base_url(self) -> str:
        db = get_database()
        connection = await db[Collections.ERP_CONNECTIONS].find_one(
            {"tenant_id": self.tenant_id, "erp": "defontana"}
        )
        return (connection or {}).get("base_url") or settings.defontana_base_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Perform an authenticated request, refreshing the token once on 401."""
        base_url = await self._base_url()
        url = f"{base_url}{path}"

        async def _do(token: str) -> httpx.Response:
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                )

        token = await self.token_manager.get_valid_token(self.tenant_id)
        resp = await _do(token)
        if resp.status_code == 401:
            # Section 7.1: on an auth failure, refresh exactly once.
            token = await self.token_manager.refresh_token(self.tenant_id)
            resp = await _do(token)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return None

    # ------------------------------------------------------------------
    async def authenticate(self) -> str:
        return await self.token_manager.get_valid_token(self.tenant_id)

    async def health_check(self) -> bool:
        return await self.token_manager.check_token(self.tenant_id)

    async def get_products(self) -> List[Dict[str, Any]]:
        if self.mock:
            return list(mock_data.MOCK_PRODUCTS)
        data = await self._request("GET", "/sale/GetSimpleProducts")
        return _as_list(data)

    async def get_product_by_barcode(self, barcode: str) -> Optional[Dict[str, Any]]:
        if self.mock:
            for product in mock_data.MOCK_PRODUCTS:
                if product.get("BarCode") == barcode:
                    return product
            return None
        data = await self._request(
            "GET", "/sale/GetProductsPOSByBarCode", params={"barCode": barcode}
        )
        items = _as_list(data)
        return items[0] if items else None

    async def get_warehouses(self) -> List[Dict[str, Any]]:
        if self.mock:
            return list(mock_data.MOCK_STORAGES)
        data = await self._request("GET", "/sale/GetStorages")
        return _as_list(data)

    async def get_orders(
        self, from_date: str, to_date: str, page: int = 1, items_per_page: int = 50
    ) -> List[Dict[str, Any]]:
        if self.mock:
            return list(mock_data.MOCK_ORDERS)
        data = await self._request(
            "GET",
            "/Order/List",
            params={
                "fromDate": from_date,
                "toDate": to_date,
                "page": page,
                "itemsPerPage": items_per_page,
            },
        )
        return _as_list(data)

    async def dispatch_order(self, order_number: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.mock:
            return mock_data.mock_dispatch_response(order_number)
        return await self._request(
            "POST", "/Order/DispatchOrder", json={"orderNumber": order_number, **payload}
        )

    async def create_inventory_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.mock:
            return mock_data.mock_inventory_response(
                payload.get("externalDocumentID", "unknown")
            )
        return await self._request("PUT", "/Inventory/Insert", json=payload)

    async def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Push a new product to Defontana.

        La integración actual sólo LEE productos desde Defontana; su API no expone
        (o no se ha confirmado) un endpoint de creación de productos. En mock se
        simula el alta; en modo real queda pendiente de conectar el endpoint real.
        """
        if self.mock:
            return mock_data.mock_create_product_response(payload.get("Code", "unknown"))
        raise NotImplementedError(
            "Crear producto en Defontana no está implementado: falta confirmar el "
            "endpoint real de la API. Conectar aquí cuando esté disponible."
        )

    async def create_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Push a new sales order to Defontana.

        Igual que create_product: hoy los pedidos sólo se LEEN desde Defontana.
        En mock se simula; en real queda pendiente del endpoint real.
        """
        if self.mock:
            return mock_data.mock_create_order_response(payload.get("Number", "unknown"))
        raise NotImplementedError(
            "Crear pedido en Defontana no está implementado: falta confirmar el "
            "endpoint real de la API. Conectar aquí cuando esté disponible."
        )

    async def get_inventory_document_by_external_id(
        self, external_document_id: str
    ) -> Optional[Dict[str, Any]]:
        if self.mock:
            # In mock mode no prior document exists, so an insert can proceed.
            return None
        try:
            return await self._request(
                "GET",
                "/Inventory/GetDocumentByExternalDocumentID",
                params={"externalDocumentID": external_document_id},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise


def _as_list(data: Any) -> List[Dict[str, Any]]:
    """Normalize Defontana responses that may wrap the list in a container key."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "Data", "items", "Items", "result", "Result", "products", "Products"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []
