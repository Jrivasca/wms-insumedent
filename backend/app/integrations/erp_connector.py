"""Generic ERP connector interface (section 7).

Concrete connectors (e.g. Defontana) implement this contract so the rest of the
WMS never depends on a specific ERP. Adding another ERP later means adding a new
connector + mapper, not changing business logic.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ERPConnector(ABC):
    @abstractmethod
    async def authenticate(self) -> str:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    async def get_products(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_stock_levels(self) -> List[Dict[str, Any]]:
        """Stock per product and warehouse as the ERP sees it."""
        ...

    @abstractmethod
    async def get_orders(self, from_date: str, to_date: str) -> List[Dict[str, Any]]:
        """Order headers in the window (all pages)."""
        ...

    @abstractmethod
    async def get_order(self, number: Any) -> Optional[Dict[str, Any]]:
        """Full order with its lines."""
        ...

    @abstractmethod
    async def dispatch_order(self, order_number: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def create_inventory_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def get_inventory_document_by_external_id(
        self, external_document_id: str
    ) -> Optional[Dict[str, Any]]:
        ...
