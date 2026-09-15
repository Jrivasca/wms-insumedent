"""Translate Defontana payloads into WMS documents (DefontanaMapper).

Campos reales (camelCase) verificados contra la API de pruebas. Defontana marca los
indicadores de maestro como ``"S"``/``"N"``.
"""
from typing import Any, Dict, List, Optional


def _qty(value: Any) -> Any:
    """Defontana envía las cantidades como float (``14.0``): entero si es exacto, para que
    calce con las cantidades escaneadas en picking."""
    value = value or 0
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _yes(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().upper() == "S"
    return bool(value)


class DefontanaMapper:
    @staticmethod
    def order_status_code(status: Optional[str]) -> str:
        """``"EEX (EN_DESPACHO_EN_FACTURACION)"`` → ``"EEX"``."""
        return (status or "").split(" ", 1)[0].strip().upper()

    @staticmethod
    def is_pending_dispatch(status: Optional[str]) -> bool:
        """La 1ª letra del código es el eje despacho: ``E`` = en despacho (el WMS lo
        prepara), ``D`` = ya despachado. La 2ª es facturación y la 3ª prestación."""
        code = DefontanaMapper.order_status_code(status)
        return code[:1] == "E"

    @staticmethod
    def map_product(raw: Dict[str, Any]) -> Dict[str, Any]:
        # Defontana no entrega marca, familia ni código de barras en este listado: no se
        # incluyen, para no pisar lo que haya cargado el importador de Excel.
        code = raw.get("code")
        return {
            "erp_product_id": code,
            "sku": code,
            "name": raw.get("name") or "",
            "description": raw.get("detailedDescription") or None,
            "unit": raw.get("unit") or "UN",
            "uses_lots": bool(raw.get("usesLotes", False)),
            "uses_serials": bool(raw.get("usesSeries", False)),
            # ``type``: "A" = artículo; "S" = servicio.
            "is_service": str(raw.get("type") or "A").upper() == "S",
            "is_active": _yes(raw.get("active")),
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_warehouse(raw: Dict[str, Any]) -> Dict[str, Any]:
        code = raw.get("code")
        return {
            "erp_storage_code": str(code),
            "name": raw.get("description") or str(code),
            "sale_available": _yes(raw.get("saleAvailable")),
            "is_active": _yes(raw.get("active")),
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_order(header: Dict[str, Any], order: Dict[str, Any]) -> Dict[str, Any]:
        """``header`` = ítem de ``Order/List``; ``order`` = ``orderData`` de ``Order/Get``."""
        client = order.get("client") or {}
        details = sorted(order.get("details") or [], key=lambda d: d.get("line") or 0)
        lines: List[Dict[str, Any]] = [
            {
                "sku": d.get("code"),
                "name": d.get("name"),
                "unit": d.get("unit") or "UN",
                "ordered_quantity": _qty(d.get("count")),
            }
            for d in details
            if not d.get("isService")  # los servicios no se pickean
        ]
        return {
            "erp_order_number": str(order.get("number") or header.get("number")),
            "erp_document_id": None,
            "erp_status": header.get("status") or order.get("status"),
            "customer": client.get("name") if isinstance(client, dict) else None,
            "order_date": order.get("creationDate") or header.get("creationDate"),
            "delivery_date": order.get("expirationDate"),
            "lines": lines,
            "raw_erp_data": {"header": header, "order": order},
        }

    @staticmethod
    def map_product_by_barcode(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        return DefontanaMapper.map_product(raw)
