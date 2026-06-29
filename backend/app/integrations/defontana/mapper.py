"""Translate Defontana payloads into WMS documents (DefontanaMapper)."""
from typing import Any, Dict, List, Optional


class DefontanaMapper:
    @staticmethod
    def map_product(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "erp_product_id": raw.get("Id") or raw.get("Code"),
            "sku": raw.get("Code") or raw.get("Id"),
            "name": raw.get("Name", ""),
            "description": raw.get("Description"),
            "unit": raw.get("Unit", "UN"),
            "brand": raw.get("Brand"),
            "category": raw.get("Family") or raw.get("Category"),
            "uses_lots": bool(raw.get("UseLot", False)),
            "uses_serials": bool(raw.get("UseSerial", False)),
            "is_service": bool(raw.get("IsService", False)),
            "barcode": raw.get("BarCode") or raw.get("Barcode"),
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_warehouse(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "erp_storage_code": str(raw.get("Code")),
            "name": raw.get("Name", ""),
            "sale_available": bool(raw.get("SaleAvailable", True)),
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_order(raw: Dict[str, Any]) -> Dict[str, Any]:
        client = raw.get("Client") or {}
        customer = client.get("Name") if isinstance(client, dict) else str(client)
        lines: List[Dict[str, Any]] = []
        for detail in raw.get("Detail", []) or []:
            lines.append(
                {
                    "sku": detail.get("Code"),
                    "name": detail.get("Name"),
                    "unit": detail.get("Unit", "UN"),
                    "ordered_quantity": detail.get("Quantity", 0),
                }
            )
        return {
            "erp_order_number": str(raw.get("Number")),
            "erp_document_id": raw.get("DocumentId"),
            "customer": customer,
            "order_date": raw.get("Date"),
            "delivery_date": raw.get("DeliveryDate"),
            "lines": lines,
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_product_by_barcode(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        return DefontanaMapper.map_product(raw)
