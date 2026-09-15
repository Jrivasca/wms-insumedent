"""Defontana ERP connector (real HTTPX client + mock mode).

When ``DEFONTANA_MOCK=true`` the connector returns simulated data and performs no
network calls. Mock responses are explicitly flagged with ``"mock": true`` so a
simulated success can never be mistaken for a real one (section 18).

Formas reales de la API (verificadas contra replapi.defontana.com, 2026-09-15):
- JSON en camelCase. Cada respuesta viene en un sobre ``{success, message,
  exceptionMessage, ...}`` con la lista bajo una clave propia (``storageList``,
  ``productList``, ``items``).
- Los listados son paginados y los parámetros de página son obligatorios.
- ``success: false`` con HTTP 200 es un error: se levanta ``DefontanaApiError`` para que
  una sincronización nunca termine "ok" con 0 registros por un fallo silencioso.
"""
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.tenant_db import tenant_db
from app.core.logging import get_logger
from app.models import Collections
from app.integrations.erp_connector import ERPConnector
from app.integrations.defontana import mock_data
from app.integrations.defontana.token_manager import DefontanaTokenManager

logger = get_logger(__name__)

PAGE_SIZE = 100
# Tope de seguridad por si la API no corta la paginación como se espera.
MAX_PAGES = 500

# GetSimpleProducts ``status``: 0 = todos, 1 = activos, 2 = inactivos.
PRODUCT_STATUS_ACTIVE = 1


class DefontanaApiError(Exception):
    """Defontana respondió HTTP 200 pero con ``success: false``."""


def _check_envelope(data: Any, path: str) -> Any:
    if isinstance(data, dict) and data.get("success") is False:
        message = data.get("message") or data.get("exceptionMessage") or "success=false"
        raise DefontanaApiError(f"{path}: {message}")
    return data


class DefontanaConnector(ERPConnector):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.token_manager = DefontanaTokenManager()
        self.mock = settings.defontana_mock

    async def _base_url(self) -> str:
        db = tenant_db(self.tenant_id)
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
        json: Optional[Any] = None,
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
            return _check_envelope(resp.json(), path)
        return None

    async def _paged(
        self,
        path: str,
        list_key: str,
        params: Dict[str, Any],
        *,
        page_param: str,
        size_param: str,
        first_page: int,
    ) -> List[Dict[str, Any]]:
        """Recorre todas las páginas de un listado y junta ``list_key``."""
        items: List[Dict[str, Any]] = []
        page = first_page
        for _ in range(MAX_PAGES):
            data = await self._request(
                "GET", path, params={**params, size_param: PAGE_SIZE, page_param: page}
            )
            batch = (data or {}).get(list_key) or []
            items.extend(batch)
            total = (data or {}).get("totalItems")
            if len(batch) < PAGE_SIZE or (isinstance(total, int) and len(items) >= total):
                break
            page += 1
        else:
            logger.warning("Defontana %s: se alcanzó el tope de %s páginas", path, MAX_PAGES)
        return items

    # ------------------------------------------------------------------
    async def authenticate(self) -> str:
        return await self.token_manager.get_valid_token(self.tenant_id)

    async def health_check(self) -> bool:
        return await self.token_manager.check_token(self.tenant_id)

    async def get_products(self) -> List[Dict[str, Any]]:
        """Artículos activos de la empresa (``Sale/GetSimpleProducts``)."""
        if self.mock:
            return list(mock_data.MOCK_PRODUCTS)
        return await self._paged(
            "/Sale/GetSimpleProducts", "productList", {"status": PRODUCT_STATUS_ACTIVE},
            page_param="pageNumber", size_param="itemsPerPage", first_page=1,
        )

    async def get_product_by_barcode(self, barcode: str) -> Optional[Dict[str, Any]]:
        if self.mock:
            code = mock_data.MOCK_BARCODES.get(barcode)
            return next((p for p in mock_data.MOCK_PRODUCTS if p["code"] == code), None)
        data = await self._request(
            "POST", "/Sale/GetProductsPOSByBarCode",
            params={"itemsPerPage": 10, "pageNumber": 1}, json={"code": [barcode]},
        )
        items = (data or {}).get("productList") or []
        return items[0] if items else None

    async def get_warehouses(self) -> List[Dict[str, Any]]:
        """Bodegas de la empresa (``Sale/GetStorages``)."""
        if self.mock:
            return list(mock_data.MOCK_STORAGES)
        return await self._paged(
            "/Sale/GetStorages", "storageList", {},
            page_param="pageNumber", size_param="itemsPerPage", first_page=1,
        )

    async def get_orders(self, from_date: str, to_date: str) -> List[Dict[str, Any]]:
        """Encabezados de pedidos de la ventana: ``number``, ``creationDate``,
        ``clientFileId`` y ``status``. Las líneas vienen en :meth:`get_order`."""
        if self.mock:
            return list(mock_data.MOCK_ORDERS)
        return await self._paged(
            "/Order/List", "items", {"FromDate": from_date, "ToDate": to_date},
            page_param="PageNumber", size_param="ItemsPerPage", first_page=0,
        )

    async def get_order(self, number: Any) -> Optional[Dict[str, Any]]:
        """Pedido completo (``orderData``: cliente, ``details``, totales)."""
        if self.mock:
            return mock_data.MOCK_ORDER_DETAILS.get(int(number))
        data = await self._request("GET", "/Order/Get", params={"number": number})
        return (data or {}).get("orderData")

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
        # POST (no PUT): la API REST de Defontana solo expone GET y POST; confirmado
        # contra el Swagger de pruebas (docs/entregables/Analisis-APIs-Defontana-a-contratar.md).
        return await self._request("POST", "/Inventory/Insert", json=payload)

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
